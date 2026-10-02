"""Insert one edge loop through a closed strip, including sloped polygons."""

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QAction, QBrush, QColor, QIcon, QPainter, QPen, QPixmap, QVector3D
from PySide6.QtWidgets import QToolBar

from core.history import SnapshotImport
from core.topology import split_face_by_chord
from tools.base import Tool


_app = None
_tool = None


def _midpoint(edge):
    return (edge.v0.position + edge.v1.position) * 0.5


def _loop_plan(mesh, seed):
    """Find a closed quad strip crossed by seed; return face/edge pairs."""
    if seed not in mesh.edges:
        raise ValueError("Clique em uma aresta da malha ativa.")
    pairs = {}
    seen_edges = {seed}
    pending = [seed]
    while pending:
        edge = pending.pop()
        if len(edge.faces) != 2:
            raise ValueError("O corte precisa de um anel fechado, sem bordas abertas.")
        for face in edge.faces:
            if face.hole_loops or len(face.loop) != 4:
                raise ValueError("O corte central aceita apenas faces quadriláteras sem furos.")
            loop = face.loop
            index = next((i for i in range(4)
                          if {loop[i], loop[(i + 1) % 4]} == {edge.v0, edge.v1}), None)
            if index is None:
                raise ValueError("A malha tem uma ligação de aresta inconsistente.")
            opposite = mesh.find_edge(loop[(index + 2) % 4], loop[(index + 3) % 4])
            if opposite is None:
                raise ValueError("Não foi encontrada a aresta oposta de uma face.")
            pair = frozenset((edge, opposite))
            if face in pairs:
                if frozenset(pairs[face]) != pair:
                    raise ValueError("O anel de faces se cruza; corte cancelado.")
                continue
            pairs[face] = (edge, opposite)
            if opposite not in seen_edges:
                seen_edges.add(opposite)
                pending.append(opposite)
    if len(pairs) < 2:
        raise ValueError("Não há faces suficientes para formar um loop.")
    # Verify every chord before changing topology, including non-convex faces.
    for face, (first, second) in pairs.items():
        if split_face_by_chord(face, _midpoint(first), _midpoint(second)) is None:
            raise ValueError("Uma face não aceita o corte central; nada foi alterado.")
    return pairs, seen_edges


def _plane_plan(mesh, seed):
    """Trace the closed cross-section perpendicular to the chosen edge.

    This covers triangles and n-gons that have exactly two intersections per
    face. A plane through an existing vertex or a branching cross-section is
    left unchanged because choosing its topology automatically is ambiguous.
    """
    if seed not in mesh.edges or len(seed.faces) != 2:
        raise ValueError("Clique em uma aresta compartilhada por duas faces.")
    plane_point = _midpoint(seed)
    normal = seed.v1.position - seed.v0.position
    if normal.lengthSquared() < 1e-12:
        raise ValueError("A aresta escolhida tem comprimento zero.")
    normal.normalize()
    tolerance = 1e-6
    points = {}

    def intersection(edge):
        if edge in points:
            return points[edge]
        a, b = edge.v0.position, edge.v1.position
        da = QVector3D.dotProduct(a - plane_point, normal)
        db = QVector3D.dotProduct(b - plane_point, normal)
        if abs(da) <= tolerance or abs(db) <= tolerance:
            raise ValueError("O plano passa por um vértice existente; corte cancelado.")
        if da * db >= 0:
            return None
        point = a + (b - a) * (da / (da - db))
        points[edge] = point
        return point

    if intersection(seed) is None:
        raise ValueError("Não foi encontrado um corte nessa aresta.")
    pairs = {}
    pending = [seed]
    seen_edges = {seed}
    while pending:
        crossed = pending.pop()
        if len(crossed.faces) != 2:
            raise ValueError("O corte chegou a uma borda aberta.")
        for face in crossed.faces:
            if face.hole_loops:
                raise ValueError("O corte atravessaria uma face com furo.")
            crossings = []
            loop = face.loop
            for i in range(len(loop)):
                edge = mesh.find_edge(loop[i], loop[(i + 1) % len(loop)])
                if edge is None:
                    raise ValueError("A face possui uma aresta ausente.")
                if intersection(edge) is not None:
                    crossings.append(edge)
            if len(crossings) != 2 or crossed not in crossings:
                raise ValueError("O corte se ramifica ou toca um vértice; nada foi alterado.")
            pair = frozenset(crossings)
            if face in pairs:
                if frozenset(pairs[face]) != pair:
                    raise ValueError("O corte se cruza; nada foi alterado.")
                continue
            pairs[face] = tuple(crossings)
            opposite = crossings[0] if crossings[1] is crossed else crossings[1]
            if opposite not in seen_edges:
                seen_edges.add(opposite)
                pending.append(opposite)
    if len(pairs) < 2:
        raise ValueError("Não há faces suficientes para formar um anel.")
    for face, (first, second) in pairs.items():
        if split_face_by_chord(face, points[first], points[second]) is None:
            raise ValueError("Uma face não aceita esse corte; nada foi alterado.")
    return pairs, seen_edges, points


def _plan(mesh, seed):
    """Keep the quad behavior, then use a planar cut for other closed rings."""
    try:
        pairs, edges = _loop_plan(mesh, seed)
    except ValueError:
        return _plane_plan(mesh, seed)
    return pairs, edges, {edge: _midpoint(edge) for edge in edges}


def _segments(pairs, points):
    return [(points[first], points[second])
            for first, second in pairs.values()]


def _pixel(viewport, position):
    if _app.api_version >= 2:
        xs, ys, front = _app.world_to_pixels(
            [[position.x(), position.y(), position.z()]])
        return (float(xs[0]), float(ys[0])) if front[0] else None
    return viewport._world_to_pixel(position)


def _draw_preview(viewport, painter):
    if _tool is None or viewport.active_tool is not _tool or not _tool.preview:
        return
    painter.setPen(QPen(QColor(255, 50, 185), 3, Qt.SolidLine, Qt.RoundCap))
    for a, b in _tool.preview:
        pa, pb = _pixel(viewport, a), _pixel(viewport, b)
        if pa is not None and pb is not None:
            painter.drawLine(QPointF(*pa), QPointF(*pb))


def _icon(window):
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    ink = window.palette().windowText().color()
    painter.setPen(QPen(ink, 4))
    painter.drawRect(10, 10, 44, 44)
    painter.setPen(QPen(QColor(255, 50, 185), 5, Qt.SolidLine, Qt.RoundCap))
    painter.drawLine(QPointF(10, 32), QPointF(54, 32))
    painter.setBrush(QBrush(QColor(255, 50, 185)))
    painter.drawEllipse(QPointF(10, 32), 4, 4)
    painter.drawEllipse(QPointF(54, 32), 4, 4)
    painter.end()
    return QIcon(pixmap)


def _pick(viewport, screen):
    pick = getattr(viewport, "pick_visible_edge", None) or viewport.pick_edge
    return pick(screen.x(), screen.y())


class LoopCutTool(Tool):
    name = "Corte em loop"
    description = "Cria um anel em faces quadriláteras ou numa seção plana fechada."
    shortcut = None
    uses_snap = False

    def __init__(self):
        global _tool
        _tool = self
        self.preview = []

    def on_activate(self, viewport):
        if viewport.active_tool is not self:
            viewport.set_active_tool(self)
            return
        viewport.flash_status("Corte em loop: passe sobre uma aresta e clique para cortar.", 5500)

    def on_deactivate(self, viewport):
        self.preview = []
        viewport.update()

    def on_cancel(self, viewport):
        self.preview = []
        viewport.update()

    def on_hover(self, ctx):
        viewport = ctx.viewport
        edge = _pick(viewport, ctx.screen)
        try:
            pairs, _edges, points = _plan(viewport.scene.mesh, edge)
            self.preview = _segments(pairs, points)
        except (ValueError, AttributeError):
            self.preview = []
        viewport.update()

    def on_click(self, ctx):
        viewport = ctx.viewport
        edge = _pick(viewport, ctx.screen)
        try:
            pairs, crossed_edges, points = _plan(viewport.scene.mesh, edge)
        except (ValueError, AttributeError) as exc:
            viewport.flash_status(str(exc), 5500)
            return

        # SnapshotImport makes all cuts and face replacements one undo step.
        # The mesh's split_edge updates every face sharing each crossed edge.
        def mutate(scene):
            mesh = scene.mesh
            for item, point in points.items():
                mesh.split_edge(item, point)
            for face, (first, second) in pairs.items():
                split = split_face_by_chord(face, points[first], points[second])
                if split is None:
                    raise RuntimeError("Não foi possível dividir uma face; alteração desfeita.")
                attrs = dict(face.attrs)
                mesh.remove_face(face)
                for vertices in split:
                    new_face = mesh.add_face(vertices)
                    new_face.attrs.update(attrs)

        viewport.history.execute(SnapshotImport(mutate))
        if viewport.history.last_error:
            self.preview = []
            viewport.update()
            viewport.flash_status(f"Corte cancelado: {viewport.history.last_error}", 5500)
            return
        viewport.scene.clear_selection()
        viewport.notify_scene_changed()
        self.preview = []
        viewport.update()
        viewport.flash_status(f"Loop criado com {len(pairs)} cortes. Ctrl+Z desfaz.", 4500)


def setup(app):
    global _app
    if app.api_version not in (1, 2):
        raise RuntimeError(f"Corte em loop requer API 1 ou 2; encontrada {app.api_version}")
    _app = app
    app.add_overlay(_draw_preview)
    toolbar = QToolBar("LoopTools", app.window)
    toolbar.setObjectName("loop_cut_toolbar")
    toolbar.setMovable(True)
    toolbar.setFloatable(True)
    toolbar.setAllowedAreas(Qt.AllToolBarAreas)
    reference = next((item for item in app.window.findChildren(QToolBar)
                      if item is not toolbar), None)
    if reference is not None:
        toolbar.setIconSize(reference.iconSize())
    toolbar.setToolButtonStyle(Qt.ToolButtonIconOnly)
    app.window.addToolBar(Qt.TopToolBarArea, toolbar)
    action = QAction(_icon(app.window), "Corte em loop", toolbar)
    action.setToolTip("Passe sobre uma aresta para prever; clique para cortar o anel")
    action.triggered.connect(lambda _checked=False: _tool.on_activate(app.viewport))
    toolbar.addAction(action)
