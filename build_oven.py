"""Изометрическая печь для пиксель-арта: 4 стадии прокачки + герой-кадр.

Запуск внутри Blender:
    exec(open(r"D:/Projects/oven-iso/build_oven.py", encoding="utf-8").read())
    build_all(); setup_stage(); render_all()

Модель строится «лицом» в -Y, корень поворачивается на 26°, камера — ортографическая изометрия.
Кладка кладётся рядами: длина блока считается по хорде сектора, поэтому щелей между камнями нет.
"""
import math
import random
from pathlib import Path

import bmesh
import bpy
from mathutils import Matrix, Vector

ROOT = Path(r"D:/Projects/oven-iso")
TEX = ROOT / "textures"

BASE_H = 0.55          # высота каменного подиума
DOME_R = 0.86          # радиус купола
CHAMBER_R = 0.62       # радиус топки
OPEN_W, OPEN_H = 0.98, 0.52   # проём: ширина и высота прямой части
FRONT_Y = -0.80
ARCH_R = OPEN_W / 2 + 0.12    # радиус оси арки
CHIM_Z = BASE_H + DOME_R * 0.60
NICHE_Y = -0.73                # центр ниши дровника в подиуме

PAL = {
    "stone_l": (0.46, 0.42, 0.35),
    "stone_m": (0.34, 0.31, 0.26),
    "stone_d": (0.22, 0.20, 0.18),
    "stone_w": (0.40, 0.34, 0.26),     # тёплый камень: разнообразие кладки
    "clay": (0.50, 0.36, 0.20),
    "clay_d": (0.33, 0.23, 0.13),
    "wood": (0.30, 0.18, 0.09),
    "wood_l": (0.46, 0.30, 0.15),
    "iron": (0.12, 0.11, 0.11),
    "ash": (0.22, 0.20, 0.19),
    "wicker": (0.52, 0.37, 0.19),
    "wicker_d": (0.26, 0.17, 0.08),
    "potato": (0.80, 0.63, 0.29),
    "ember": (0.95, 0.25, 0.05),
    "rune": (0.25, 0.75, 1.0),
    "soot": (0.09, 0.08, 0.08),
    "hearth": (0.24, 0.16, 0.12),
}
STONES = ("stone_l", "stone_m", "stone_w", "stone_l", "stone_m")


# ------------------------------------------------------------------ материалы

def _inp(node, ident):
    return next(s for s in node.inputs if s.identifier == ident)


def mat(name, color, rough=0.85, metal=0.0, emit=None, strength=0.0, image=None):
    m = bpy.data.materials.get(name)
    if m:
        return m
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    _inp(b, "Base Color").default_value = (*color, 1)
    _inp(b, "Roughness").default_value = rough
    _inp(b, "Metallic").default_value = metal
    if emit:
        _inp(b, "Emission Color").default_value = (*emit, 1)
        _inp(b, "Emission Strength").default_value = strength
    if image:
        t = m.node_tree.nodes.new("ShaderNodeTexImage")
        t.image = bpy.data.images.load(str(image), check_existing=True)
        t.interpolation = "Closest"
        t.location = (-400, 0)
        m.node_tree.links.new(t.outputs["Color"], _inp(b, "Base Color"))
        m.node_tree.links.new(t.outputs["Alpha"], _inp(b, "Alpha"))   # фон текстуры прозрачен
        try:
            m.surface_render_method = "BLENDED"
        except (AttributeError, TypeError):
            pass
        if strength:
            m.node_tree.links.new(t.outputs["Color"], _inp(b, "Emission Color"))
            _inp(b, "Emission Strength").default_value = strength
    m.diffuse_color = (*color, 1)
    return m


def P(key, **kw):
    return mat(key, PAL[key], **kw)


def ember_mat(strength=6.0):
    return mat(f"ember_{strength}", PAL["ember"], rough=0.5, emit=(1.0, 0.40, 0.09), strength=strength)


# ------------------------------------------------------------------ геометрия

class Builder:
    """Собирает объект из множества примитивов в общий bmesh: низкополигонально, плоское затенение."""

    def __init__(self, name, coll, root):
        self.name, self.coll, self.root = name, coll, root
        self.bm = bmesh.new()
        self.mats = []

    def _mi(self, material):
        if material not in self.mats:
            self.mats.append(material)
        return self.mats.index(material)

    def _finish(self, before, verts, material, jitter=0.0, rnd=None, bevel=0.0):
        """Материал назначается после фаски: bevel пересоздаёт грани и старые ссылки становятся невалидны."""
        if jitter and rnd:
            for v in verts:
                v.co += Vector([rnd.uniform(-jitter, jitter) for _ in range(3)])
        if bevel:
            edges = list({e for v in verts for e in v.link_edges})
            bmesh.ops.bevel(self.bm, geom=edges, offset=bevel, segments=1, affect="EDGES")
        mi = self._mi(material)
        for f in self.bm.faces:
            if f not in before:
                f.material_index = mi
                f.smooth = False

    def cube(self, size, loc, material, rot=(0, 0, 0), jitter=0.0, rnd=None, bevel=0.0):
        before = set(self.bm.faces)
        r = bmesh.ops.create_cube(self.bm, size=1.0)["verts"]
        bmesh.ops.scale(self.bm, vec=Vector(size), verts=r)
        m = Matrix.Rotation(rot[2], 3, "Z") @ Matrix.Rotation(rot[1], 3, "Y") @ Matrix.Rotation(rot[0], 3, "X")
        bmesh.ops.rotate(self.bm, verts=r, cent=(0, 0, 0), matrix=m)
        bmesh.ops.translate(self.bm, vec=Vector(loc), verts=r)
        self._finish(before, r, material, jitter, rnd, bevel)
        return r

    def cyl(self, r1, r2, depth, loc, material, rot=(0, 0, 0), seg=16):
        before = set(self.bm.faces)
        vs = bmesh.ops.create_cone(self.bm, cap_ends=True, segments=seg,
                                   radius1=r1, radius2=r2, depth=depth)["verts"]
        m = Matrix.Rotation(rot[2], 3, "Z") @ Matrix.Rotation(rot[1], 3, "Y") @ Matrix.Rotation(rot[0], 3, "X")
        bmesh.ops.rotate(self.bm, verts=vs, cent=(0, 0, 0), matrix=m)
        bmesh.ops.translate(self.bm, vec=Vector(loc), verts=vs)
        self._finish(before, vs, material)
        return vs

    def ring(self, r, tube, loc, material, seg=14, tube_seg=6):
        """Обод — для корзин."""
        rings = []
        for i in range(seg):
            a = 2 * math.pi * i / seg
            c = Vector((r * math.cos(a), r * math.sin(a), 0))
            n = Vector((math.cos(a), math.sin(a), 0))
            z = Vector((0, 0, 1))
            rings.append([self.bm.verts.new(Vector(loc) + c + tube * (math.cos(t) * n + math.sin(t) * z))
                          for t in (2 * math.pi * k / tube_seg for k in range(tube_seg))])
        mi = self._mi(material)
        for i in range(seg):
            r0, r1 = rings[i], rings[(i + 1) % seg]
            for k in range(tube_seg):
                f = self.bm.faces.new((r0[k], r0[(k + 1) % tube_seg], r1[(k + 1) % tube_seg], r1[k]))
                f.material_index = mi
                f.smooth = False

    def ico(self, r, loc, material, scale=(1, 1, 1), subdiv=2, jitter=0.0, rnd=None, rot_z=0.0):
        before = set(self.bm.faces)
        try:
            vs = bmesh.ops.create_icosphere(self.bm, subdivisions=subdiv, radius=r)["verts"]
        except TypeError:
            vs = bmesh.ops.create_icosphere(self.bm, subdivisions=subdiv, diameter=r)["verts"]
        bmesh.ops.scale(self.bm, vec=Vector(scale), verts=vs)
        if rot_z:
            bmesh.ops.rotate(self.bm, verts=vs, cent=(0, 0, 0), matrix=Matrix.Rotation(rot_z, 3, "Z"))
        bmesh.ops.translate(self.bm, vec=Vector(loc), verts=vs)
        self._finish(before, vs, material, jitter, rnd)
        return vs

    def object(self):
        me = bpy.data.meshes.new(self.name)
        self.bm.to_mesh(me)
        self.bm.free()
        for m in self.mats:
            me.materials.append(m)
        ob = bpy.data.objects.new(self.name, me)
        self.coll.objects.link(ob)
        ob.parent = self.root
        return ob


def plane(name, w, h, matrix, material, coll, root):
    me = bpy.data.meshes.new(name)
    me.from_pydata([(-w / 2, -h / 2, 0), (w / 2, -h / 2, 0), (w / 2, h / 2, 0), (-w / 2, h / 2, 0)], [], [(0, 1, 2, 3)])
    uv = me.uv_layers.new(name="UVMap")
    for i, c in enumerate([(0, 0), (1, 0), (1, 1), (0, 1)]):
        uv.data[i].uv = c
    me.materials.append(material)
    ob = bpy.data.objects.new(name, me)
    ob.matrix_basis = matrix
    coll.objects.link(ob)
    ob.parent = root
    return ob


def boolean(target, cutter):
    """Вырезает cutter из target и применяет результат (cutter удаляется)."""
    mod = target.modifiers.new("cut", "BOOLEAN")
    mod.object, mod.operation = cutter, "DIFFERENCE"
    try:
        mod.material_mode = "TRANSFER"
    except (AttributeError, TypeError):
        pass
    bpy.context.view_layer.update()
    new = bpy.data.meshes.new_from_object(target.evaluated_get(bpy.context.evaluated_depsgraph_get()))
    target.modifiers.clear()
    old, target.data = target.data, new
    bpy.data.meshes.remove(old)
    for p in target.data.polygons:
        p.use_smooth = False
    bpy.data.objects.remove(cutter)
    return target


# ------------------------------------------------------------------ кладка

def course(b, rnd, radius, z, h, n, depth=0.25, phase=0.0, bevel=0.012, skip=None):
    """Ряд кладки: длина блока = хорда сектора, поэтому ряд смыкается без щелей.

    skip — полуширина переднего сектора в радианах: там кладки нет, остаётся ниша.
    """
    step = 2 * math.pi / n
    chord = 2 * radius * math.sin(step / 2) * 1.04
    for i in range(n):
        a = phase + step * (i + 0.5)
        if skip and abs(math.atan2(math.sin(a + math.pi / 2), math.cos(a + math.pi / 2))) < skip:
            continue
        b.cube((chord, depth * rnd.uniform(0.94, 1.06), h * rnd.uniform(0.96, 1.0)),
               (radius * math.cos(a), radius * math.sin(a), z + h / 2),
               P(rnd.choice(STONES)), rot=(0, 0, a + math.pi / 2),
               jitter=0.005, rnd=rnd, bevel=bevel)


def platform(b, rnd, niche=True):
    """Подиум: три ряда кладки вперевязку, ниша под подом и карниз."""
    # внутренняя стенка — тоже кладкой, иначе цилиндр закрывает нишу
    course(b, rnd, 0.68, 0.0, BASE_H, 14, depth=0.20, bevel=0.0,
           skip=0.58 if niche else None)
    for k, z in enumerate((0.0, 0.175, 0.35)):
        course(b, rnd, 0.80, z, 0.18, 12, phase=0.13 * (k % 2),
               skip=0.52 if (niche and k < 2) else None)
    if niche:                                   # углубление дровника: стенки внутри, проём — пропуск кладки
        b.cube((0.78, 0.05, 0.38), (0, NICHE_Y + 0.21, 0.175), P("soot"))          # задняя стенка
        for sx in (-1, 1):
            b.cube((0.05, 0.34, 0.38), (sx * 0.40, NICHE_Y + 0.05, 0.175), P("soot"))     # боковины
        b.cube((0.78, 0.38, 0.05), (0, NICHE_Y + 0.03, 0.02), P("stone_d"))               # пол
        b.cube((0.86, 0.34, 0.07), (0, NICHE_Y + 0.04, 0.39), P("stone_m"), bevel=0.012)  # перемычка
    b.cyl(0.91, 0.90, 0.07, (0, 0, BASE_H - 0.015), P("stone_m"), seg=18)     # карниз
    b.cyl(0.86, 0.86, 0.03, (0, 0, BASE_H + 0.02), P("stone_l"), seg=18)


def arch(b, rnd, jamb_h=0.175):
    """Свод проёма из клиновых блоков и боковые столбы под ним."""
    n = 13
    step = math.pi / n
    thick = 2 * ARCH_R * math.sin(step / 2) * 1.06
    zc = BASE_H + OPEN_H - 0.02
    for i in range(n):
        a = step * (i + 0.5)
        b.cube((0.22, 0.28, thick),
               (ARCH_R * math.cos(a), FRONT_Y + 0.07, zc + ARCH_R * math.sin(a)),
               P(rnd.choice(STONES)), rot=(0, -a, 0), jitter=0.004, rnd=rnd, bevel=0.012)
    rows = max(1, int(round((zc - BASE_H) / jamb_h)))
    for sx in (-1, 1):
        for k in range(rows):
            b.cube((0.22, 0.28, jamb_h * 1.03), (sx * ARCH_R, FRONT_Y + 0.07, BASE_H + jamb_h * (k + 0.5)),
                   P(rnd.choice(STONES)), jitter=0.004, rnd=rnd, bevel=0.012)


def chimney(b, rnd):
    """Труба: основание утоплено в купол, сверху карниз и устье."""
    b.cube((0.38, 0.36, 0.66), (0, 0.0, CHIM_Z + 0.16), P("stone_m"), jitter=0.005, rnd=rnd, bevel=0.014)
    b.cube((0.42, 0.40, 0.06), (0, 0.0, CHIM_Z + 0.52), P("stone_l"), jitter=0.004, rnd=rnd, bevel=0.012)
    b.cube((0.16, 0.15, 0.05), (0, 0.0, CHIM_Z + 0.56), P("soot"))            # устье
    for sx in (-1, 1):                                                        # опорные камни у основания
        b.cube((0.13, 0.32, 0.18), (sx * 0.24, 0.0, CHIM_Z + 0.02), P(rnd.choice(STONES)),
               rot=(0, sx * 0.25, 0), jitter=0.004, rnd=rnd, bevel=0.01)


def dome(coll, root, rnd, cracked=False):
    """Глиняный купол с топкой и проёмом."""
    b = Builder("Dome", coll, root)
    b.ico(DOME_R, (0, 0, BASE_H), P("clay"), scale=(1.0, 1.0, 0.95), subdiv=3, jitter=0.010, rnd=rnd)
    ob = b.object()

    def cut(fn):                      # резаки по одному: пересекающиеся ломают булеву операцию
        c = Builder("cut", coll, root)
        fn(c)
        boolean(ob, c.object())

    cut(lambda c: c.cube((3, 3, 1.2), (0, 0, BASE_H - 0.6), P("soot")))
    cut(lambda c: c.ico(CHAMBER_R, (0, 0, BASE_H + 0.02), P("soot"), scale=(1, 1, 0.92), subdiv=3))
    cut(lambda c: c.cube((OPEN_W, 2.0, OPEN_H), (0, -0.7, BASE_H + OPEN_H / 2 - 0.02), P("soot")))
    cut(lambda c: c.cyl(OPEN_W / 2, OPEN_W / 2, 2.0, (0, -0.7, BASE_H + OPEN_H - 0.02), P("soot"),
                        rot=(math.pi / 2, 0, 0), seg=18))
    # внутренние грани свода: перенос материала булевой операцией ненадёжен, красим по положению
    soot = P("hearth")
    if soot.name not in [m.name for m in ob.data.materials]:
        ob.data.materials.append(soot)
    idx = [m.name for m in ob.data.materials].index(soot.name)
    centre = Vector((0, 0, BASE_H + 0.02))
    for poly in ob.data.polygons:
        if (poly.center - centre).length < CHAMBER_R + 0.04:
            poly.material_index = idx

    if cracked:
        c = Builder("Cracks", coll, root)
        for _ in range(8):
            az = rnd.uniform(-2.0, 2.0)
            el = rnd.uniform(0.2, 1.0)                 # угол подъёма по куполу
            r = DOME_R - 0.012
            p = (r * math.cos(el) * math.cos(az), r * math.cos(el) * math.sin(az),
                 BASE_H + r * 0.95 * math.sin(el))
            # трещина лежит на поверхности: длинная ось по меридиану, толщина минимальна
            c.cube((0.022, rnd.uniform(0.10, 0.22), 0.018), p, P("clay_d"),
                   rot=(0, -(math.pi / 2 - el), az + math.pi / 2))
        c.object()
    return ob


# ------------------------------------------------------------------ содержимое топки

def hearth(b, rnd, hot=False):
    """Под печи: камень, слой золы и (на последней стадии) угли."""
    b.cyl(CHAMBER_R - 0.02, CHAMBER_R - 0.03, 0.06, (0, 0.02, BASE_H + 0.01), P("stone_d"), seg=18)
    b.cyl(CHAMBER_R - 0.10, CHAMBER_R - 0.12, 0.02, (0, 0.04, BASE_H + 0.05), P("ash"), seg=18)
    if not hot:
        return
    for _ in range(14):
        a, r = rnd.uniform(-2.5, -0.6), rnd.uniform(0.14, CHAMBER_R - 0.14)
        b.ico(rnd.uniform(0.04, 0.07), (r * math.cos(a), r * math.sin(a), BASE_H + 0.06),
              ember_mat(6.0) if rnd.random() > 0.5 else P("soot"), subdiv=1, jitter=0.008, rnd=rnd)


def potatoes(b, rnd, n=3):
    for x, y in [(-0.18, 0.06), (0.15, -0.01), (-0.01, 0.23), (0.22, 0.19)][:n]:
        b.ico(0.13, (x, y - 0.04, BASE_H + 0.13), P("potato"),
              scale=(1.25, 0.95, 0.82), subdiv=2, jitter=0.010, rnd=rnd, rot_z=rnd.uniform(0, 3))


def firebox(b, rnd):
    """Поддувало в нише подиума: чугунная рама, решётка и светящиеся щели."""
    y = NICHE_Y - 0.12
    b.cube((0.70, 0.06, 0.32), (0, y + 0.06, 0.19), ember_mat(7.0))            # жар за решёткой
    for i in range(6):
        b.cube((0.035, 0.09, 0.34), (-0.29 + i * 0.116, y, 0.19), P("iron"), bevel=0.006)
    for dz in (-0.18, 0.18):
        b.cube((0.78, 0.11, 0.05), (0, y, 0.19 + dz), P("iron"), bevel=0.01)
    for dx in (-0.37, 0.37):
        b.cube((0.05, 0.11, 0.41), (dx, y, 0.19), P("iron"), bevel=0.01)


def firewood(b, rnd):
    """Дрова, сложенные в нишу подиума."""
    for row, (n, z) in enumerate(((3, 0.09), (2, 0.24))):
        for i in range(n):
            b.cyl(0.07, 0.07, 0.34, ((i - (n - 1) / 2) * 0.155 + row * 0.07, NICHE_Y + 0.02, z),
                  P("wood") if (i + row) % 2 else P("wood_l"),
                  rot=(math.pi / 2, 0, rnd.uniform(-0.05, 0.05)), seg=10)


def sparks(b, rnd, n=7):
    m = mat("spark", (1.0, 0.55, 0.15), rough=0.4, emit=(1.0, 0.50, 0.12), strength=4.0)
    for _ in range(n):
        s = rnd.uniform(0.03, 0.05)
        b.cube((s, s, s), (rnd.uniform(-0.4, 0.4), FRONT_Y - rnd.uniform(0.02, 0.22),
                           BASE_H + rnd.uniform(0.95, 1.5)), m)


# ------------------------------------------------------------------ окружение

def bench(b, rnd, baskets=0):
    x, y0 = 1.32, 0.05
    for dy in (-0.12, 0.12):
        b.cube((1.02, 0.21, 0.07), (x, y0 + dy, 0.60), P("wood_l"), jitter=0.004, rnd=rnd, bevel=0.008)
    for dx, dy in ((-0.40, -0.15), (0.40, -0.15), (-0.40, 0.22), (0.40, 0.22)):
        b.cube((0.085, 0.085, 0.57), (x + dx, y0 + dy, 0.285), P("wood"), bevel=0.008)
    b.cube((0.98, 0.05, 0.06), (x, y0, 0.34), P("wood"), bevel=0.006)
    for i in range(baskets):
        bx, by = x - 0.26 + i * 0.5, y0 + (0.05 if i else -0.05)
        b.cyl(0.155, 0.20, 0.26, (bx, by, 0.77), P("wicker"), seg=12)
        b.cyl(0.135, 0.18, 0.24, (bx, by, 0.79), P("wicker_d"), seg=12)       # внутренняя стенка
        b.cyl(0.175, 0.175, 0.012, (bx, by, 0.80), P("soot"), seg=12)         # дно в тени
        b.ring(0.192, 0.022, (bx, by, 0.895), P("wood"), seg=12)              # обод
        if i == 0:                                                            # картошка в корзине
            for dx, dy in ((-0.05, 0.0), (0.05, 0.03), (0.0, -0.05)):
                b.ico(0.075, (bx + dx, by + dy, 0.90), P("potato"),
                      scale=(1.2, 0.95, 0.8), subdiv=2, jitter=0.006, rnd=rnd, rot_z=rnd.uniform(0, 3))


def woodpile(b, rnd):
    """Поленница слева от печи."""
    x, y = -0.88, 0.12
    for row, (n, z) in enumerate(((3, 0.085), (2, 0.245))):
        for i in range(n):
            b.cyl(0.082, 0.082, 0.50, (x + (i - (n - 1) / 2) * 0.17 + row * 0.08, y, z),
                  P("wood") if (i + row) % 2 else P("wood_l"),
                  rot=(0, math.pi / 2, rnd.uniform(-0.08, 0.08)), seg=10)
    b.cyl(0.082, 0.082, 0.48, (x + 0.04, y, 0.395), P("wood_l"), rot=(0, math.pi / 2, 0.05), seg=10)


def peel(b, rnd):
    """Лопата для печи, прислонённая к лавке."""
    ang = math.radians(16)
    base = Vector((0.86, -0.30, 0.0))
    d = Vector((math.sin(ang), 0.0, math.cos(ang)))
    b.cube((0.045, 0.045, 1.05), base + d * 0.52, P("wood"), rot=(0, -ang, 0), bevel=0.006)
    b.cube((0.28, 0.035, 0.30), base + d * 1.12, P("wood_l"), rot=(0, -ang, 0), bevel=0.006)


# ------------------------------------------------------------------ руны

def rune_panels(coll, root, tier):
    s = 3.4 if tier >= 4 else 2.2
    mats = [mat(f"rune_{i}_t{tier}", PAL["rune"], rough=0.4, emit=(0.35, 0.85, 1.0),
                strength=s, image=TEX / f"rune_{i}.png") for i in range(4)]
    rnd = random.Random(7 + tier)
    y = FRONT_Y - 0.08
    zc = BASE_H + OPEN_H - 0.02
    for sx in (-1, 1):                                   # на боковых столбах
        for k in (0, 1, 2):
            mtx = (Matrix.Translation((sx * ARCH_R, y, BASE_H + 0.175 * (k + 0.5)))
                   @ Matrix.Rotation(math.radians(90), 4, "X"))
            plane(f"Rune{sx}{k}", 0.17, 0.15, mtx, rnd.choice(mats), coll, root)
    n = 13
    for i in (2, 6, 10):                                 # на своде
        a = math.pi * (i + 0.5) / n
        mtx = (Matrix.Translation((ARCH_R * math.cos(a), y, zc + ARCH_R * math.sin(a)))
               @ Matrix.Rotation(math.radians(90), 4, "X"))
        plane(f"RuneA{i}", 0.16, 0.14, mtx, rnd.choice(mats), coll, root)
    mtx = Matrix.Translation((0, -0.195, CHIM_Z + 0.26)) @ Matrix.Rotation(math.radians(90), 4, "X")
    plane("RuneChimney", 0.22, 0.24, mtx, mats[0], coll, root)


# ------------------------------------------------------------------ стадии

def build_tier(tier):
    name = f"Oven_T{tier}"
    old = bpy.data.collections.get(name)
    if old:
        for ob in list(old.objects):
            bpy.data.objects.remove(ob)
        bpy.data.collections.remove(old)
    coll = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(coll)
    root = bpy.data.objects.new(name, None)
    root.rotation_euler = (0, 0, math.radians(26))
    coll.objects.link(root)
    rnd = random.Random(20 + tier)

    b = Builder(f"Body_T{tier}", coll, root)
    if tier == 1:                                        # костровище
        course(b, rnd, 0.70, 0.0, 0.20, 11, depth=0.22)
        course(b, rnd, 0.66, 0.19, 0.14, 9, depth=0.20, phase=0.2)
        b.cyl(0.60, 0.58, 0.08, (0, 0, 0.05), P("ash"), seg=16)
        for i, a in enumerate((0.5, 2.0, 3.6, 5.1)):     # прогоревшие поленья
            b.cyl(0.055, 0.055, 0.46, (0.13 * math.cos(a), 0.13 * math.sin(a), 0.11),
                  P("soot") if i % 2 else P("wood"), rot=(0, math.pi / 2, a), seg=8)
        b.ico(0.07, (0.05, -0.05, 0.10), P("soot"), subdiv=1, jitter=0.01, rnd=rnd)
        bench(b, rnd)
        b.object()
        return coll

    platform(b, rnd)
    arch(b, rnd)
    hearth(b, rnd, hot=tier >= 4)
    peel(b, rnd)
    if tier >= 3:
        chimney(b, rnd)
        potatoes(b, rnd, n=3)
    if tier >= 4:
        firebox(b, rnd)
        sparks(b, rnd)
    else:
        firewood(b, rnd)
    bench(b, rnd, baskets=0 if tier == 2 else 2)
    b.object()
    dome(coll, root, rnd, cracked=tier >= 4)
    if tier >= 3:
        rune_panels(coll, root, tier)
    if tier >= 4:
        li = bpy.data.lights.new(f"Fire_T{tier}", "POINT")
        li.energy, li.color, li.shadow_soft_size = 8, (1.0, 0.42, 0.12), 0.25
        ob = bpy.data.objects.new(f"Fire_T{tier}", li)
        ob.location = (0, 0.02, BASE_H + 0.22)
        coll.objects.link(ob)
        ob.parent = root
    return coll


LAYOUT_GAP = 6.0


def build_all():
    for t in (1, 2, 3, 4):
        coll = build_tier(t)
        root = next(o for o in coll.objects if o.type == "EMPTY")
        root.location = ((t - 1) * LAYOUT_GAP, 0, 0)


# ------------------------------------------------------------------ студия и рендер


def setup_stage():
    sc = bpy.context.scene
    coll = bpy.data.collections.get("Stage") or bpy.data.collections.new("Stage")
    if coll.name not in sc.collection.children:
        sc.collection.children.link(coll)
    for ob in list(coll.objects):
        bpy.data.objects.remove(ob)

    ca = bpy.data.cameras.new("ISO")
    ca.type = "ORTHO"
    ca.ortho_scale = 3.55
    cam = bpy.data.objects.new("ISO", ca)
    cam.rotation_euler = (math.radians(60), 0, math.radians(45))
    coll.objects.link(cam)
    sc.camera = cam

    key = bpy.data.lights.new("Key", "SUN")
    key.energy, key.angle, key.color = 4.6, math.radians(10), (1.0, 0.93, 0.80)
    ob = bpy.data.objects.new("Key", key)
    ob.rotation_euler = (math.radians(52), 0, math.radians(20))
    coll.objects.link(ob)

    fill = bpy.data.lights.new("Fill", "SUN")
    fill.energy, fill.color = 0.75, (0.55, 0.70, 1.0)
    ob = bpy.data.objects.new("Fill", fill)
    ob.rotation_euler = (math.radians(65), 0, math.radians(200))
    coll.objects.link(ob)

    w = sc.world or bpy.data.worlds.new("World")
    sc.world = w
    w.use_nodes = True
    bg = next(n for n in w.node_tree.nodes if n.type == "BACKGROUND")
    bg.inputs[0].default_value = (0.28, 0.30, 0.38, 1)
    bg.inputs[1].default_value = 0.22

    sc.render.film_transparent = True
    sc.render.image_settings.color_mode = "RGBA"
    sc.view_settings.view_transform = "Standard"
    try:
        sc.eevee.taa_render_samples = 64
        sc.eevee.use_raytracing = True
    except AttributeError:
        pass


def frame_tier(tier, scale, pan=(0, 0)):
    cam = bpy.data.objects["ISO"]
    cam.data.ortho_scale = scale
    target = Vector(((tier - 1) * LAYOUT_GAP, 0, 0.75))
    dirv = Vector((0.6124, -0.6124, 0.5))
    right = Vector((0.7071, 0.7071, 0.0))
    up = dirv.cross(right).normalized()
    cam.location = target + dirv * 14.0 + right * pan[0] + up * pan[1]


def render_all(size=1200, hero=2048):
    out = ROOT / "renders_hi"
    out.mkdir(exist_ok=True)
    sc = bpy.context.scene
    sc.render.resolution_percentage = 100
    done = []
    for t in (1, 2, 3, 4):
        sc.render.resolution_x = sc.render.resolution_y = size
        frame_tier(t, 3.55, pan=(0.08, -0.06))
        sc.render.filepath = str(out / f"tier{t}.png")
        bpy.ops.render.render(write_still=True)
        done.append(sc.render.filepath)
    sc.render.resolution_x = sc.render.resolution_y = hero
    frame_tier(4, 3.35, pan=(0.06, -0.05))
    sc.render.filepath = str(out / "hero.png")
    bpy.ops.render.render(write_still=True)
    done.append(sc.render.filepath)
    return done
