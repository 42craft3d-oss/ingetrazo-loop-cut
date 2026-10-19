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


def _quad_plan_from_face(mesh, face):
    """Choose the largest closed quad loop available from a picked face.

    A user points at the wall of a cylinder, not precisely at its thin
    vertical edge.  Each lateral quad has two vertical edges that lead to the
    full circumferential ring; the horizontal cap-boundary edges do not.
    Prefer the longest valid quad strip so a face click picks the useful ring.
    """
    if face is None or face.hole_loops or len(face.loop) != 4:
        raise ValueError("A face apontada não possui um loop quadrilateral.")
    candidates = []
    loop = face.loop
    for index in range(4):
        edge = mesh.find_edge(loop[index], loop[(index + 1) % 4])
        if edge is None:
            continue
        try:
            pairs, edges = _loop_plan(mesh, edge)
        except ValueError:
            continue
        candidates.append((len(pairs), pairs, edges))
    if not candidates:
        raise ValueError("A face apontada não faz parte de um loop fechado.")
    _size, pairs, edges = max(candidates, key=lambda item: item[0])
    return pairs, edges, {edge: _midpoint(edge) for edge in edges}


def _segments(pairs, points):
    return [(points[first], points[second])
            for first, second in pairs.values()]


def _edge_segments(edges):
    """Segments of the existing loop, used by the green selection overlay."""
    return [(edge.v0.position, edge.v1.position) for edge in edges]


def _ring_from_edge(mesh, seed):
    """Find the closed coplanar edge ring containing *seed*.

    This is deliberately different from :func:`_loop_plan`: an edge loop
    walks through opposite sides of quads, while a ring follows existing,
    end-to-end edges around a surface.  On a cylinder that is the horizontal
    blue/cyan contour made by a prior cut.
    """
    if seed is None or seed not in mesh.edges or not seed.faces:
        raise ValueError("Shift+clique diretamente numa aresta do anel.")
    tangent = seed.v1.position - seed.v0.position
    if tangent.lengthSquared() < 1e-12:
        raise ValueError("A aresta escolhida tem comprimento zero.")
    midpoint = _midpoint(seed)
    candidates = []
    for face in seed.faces:
        normal = face.normal()
        plane_normal = QVector3D.crossProduct(tangent, normal)
        if plane_normal.lengthSquared() < 1e-12:
            continue
        plane_normal.normalize()
        tolerance = max(1e-6, seed.length() * 1e-4)
        planar = []
        for edge in mesh.edges:
            da = QVector3D.dotProduct(edge.v0.position - midpoint, plane_normal)
            db = QVector3D.dotProduct(edge.v1.position - midpoint, plane_normal)
            if abs(da) <= tolerance and abs(db) <= tolerance:
                planar.append(edge)
        by_vertex = {}
        for edge in planar:
            by_vertex.setdefault(edge.v0, []).append(edge)
            by_vertex.setdefault(edge.v1, []).append(edge)
        component = {seed}
        pending = [seed]
        while pending:
            edge = pending.pop()
            for vertex in (edge.v0, edge.v1):
                for other in by_vertex.get(vertex, ()):
                    if other not in component:
                        component.add(other)
                        pending.append(other)
        degrees = {}
        for edge in component:
            degrees[edge.v0] = degrees.get(edge.v0, 0) + 1
            degrees[edge.v1] = degrees.get(edge.v1, 0) + 1
        if len(component) > 2 and all(degree == 2 for degree in degrees.values()):
            candidates.append(component)
    if not candidates:
        raise ValueError("Esta aresta não pertence a um anel fechado.")
    return max(candidates, key=len)


def _pixel(viewport, position):
    if _app.api_version >= 2:
        xs, ys, front = _app.world_to_pixels(
            [[position.x(), position.y(), position.z()]])
        return (float(xs[0]), float(ys[0])) if front[0] else None
    return viewport._world_to_pixel(position)


def _draw_preview(viewport, painter):
    if _tool is None or viewport.active_tool is not _tool:
        return
    for color, width, segments in (
        (QColor(75, 235, 125), 4, _tool.selected_loop),
        (QColor(75, 235, 125), 3, _tool.hover_loop),
        (QColor(0, 98, 165), 4, _tool.selected_ring),
        (QColor(0, 98, 165), 3, _tool.hover_ring),
        (QColor(255, 50, 185), 3, _tool.preview),
    ):
        painter.setPen(QPen(color, width, Qt.SolidLine, Qt.RoundCap))
        for a, b in segments:
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


def _plan_at(viewport, screen):
    """Prefer the closed quad loop from the face under the cursor.

    Falling back to edge picking preserves the former planar-section behavior
    for a deliberate click on a cap or non-quad surface.
    """
    mesh = viewport.scene.mesh
    pick_face = getattr(viewport, "pick_face", None)
    if pick_face is not None:
        face = pick_face(screen.x(), screen.y())
        try:
            return _quad_plan_from_face(mesh, face)
        except (ValueError, AttributeError):
            pass
    return _plan(mesh, _pick(viewport, screen))


def _ring_at(viewport, screen):
    """Ring selection intentionally requires an actual edge under the cursor."""
    return _ring_from_edge(viewport.scene.mesh, _pick(viewport, screen))


class LoopCutTool(Tool):
    name = "Corte em loop"
    description = "Cria um anel em faces quadriláteras ou numa seção plana fechada."
    shortcut = None
    uses_snap = False

    def __init__(self):
        global _tool
        _tool = self
        self.preview = []
        self.hover_loop = []
        self.selected_loop = []
        self.hover_ring = []
        self.selected_ring = []

    def on_activate(self, viewport):
        if viewport.active_tool is not self:
            viewport.set_active_tool(self)
            return
        viewport.flash_status(
            "Clique corta. Alt+clique: Edge Loop verde; Shift+clique: Edge Ring azul.",
            5500)

    def on_deactivate(self, viewport):
        self.preview = []
        self.hover_loop = []
        self.selected_loop = []
        self.hover_ring = []
        self.selected_ring = []
        viewport.update()

    def on_cancel(self, viewport):
        self.preview = []
        self.hover_loop = []
        self.hover_ring = []
        viewport.update()

    def on_hover(self, ctx):
        viewport = ctx.viewport
        try:
            if ctx.modifiers & Qt.ShiftModifier:
                self.preview = []
                self.hover_loop = []
                self.hover_ring = _edge_segments(_ring_at(viewport, ctx.screen))
                viewport.update()
                return
            pairs, crossed_edges, points = _plan_at(viewport, ctx.screen)
            if ctx.modifiers & Qt.AltModifier:
                self.preview = []
                self.hover_loop = _edge_segments(crossed_edges)
            else:
                self.hover_loop = []
                self.preview = _segments(pairs, points)
            self.hover_ring = []
        except (ValueError, AttributeError):
            self.preview = []
            self.hover_loop = []
            self.hover_ring = []
        viewport.update()

    def on_click(self, ctx):
        viewport = ctx.viewport
        if ctx.modifiers & Qt.ShiftModifier:
            try:
                ring = _ring_at(viewport, ctx.screen)
            except (ValueError, AttributeError) as exc:
                viewport.flash_status(str(exc), 5500)
                return
            # Shift follows the normal additive-selection convention: a
            # previously Alt-selected green loop remains genuinely selected.
            viewport.scene.select(ring, mode="add")
            self.selected_ring = _edge_segments(ring)
            self.hover_ring = []
            self.preview = []
            self.hover_loop = []
            viewport.update()
            viewport.flash_status(
                f"Anel selecionado com {len(ring)} arestas.", 3500)
            return
        try:
            pairs, crossed_edges, points = _plan_at(viewport, ctx.screen)
        except (ValueError, AttributeError) as exc:
            viewport.flash_status(str(exc), 5500)
            return
        if ctx.modifiers & Qt.AltModifier:
            viewport.scene.select(crossed_edges, mode="replace")
            self.selected_loop = _edge_segments(crossed_edges)
            self.hover_loop = []
            self.selected_ring = []
            self.hover_ring = []
            self.preview = []
            viewport.update()
            viewport.flash_status(
                f"Loop selecionado com {len(crossed_edges)} arestas.", 3500)
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
        self.hover_loop = []
        self.selected_loop = []
        self.hover_ring = []
        self.selected_ring = []
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
    action.setToolTip(
        "Clique: Loop Cut; Alt+clique: Edge Loop; Shift+clique: Edge Ring")
    action.triggered.connect(lambda _checked=False: _tool.on_activate(app.viewport))
    toolbar.addAction(action)
