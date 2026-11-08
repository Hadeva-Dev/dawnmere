# Kip the kingfisher: every pose from one parametric drawing. Flat fills, one shade per colour.
import re, itertools
BLUE, BLUE_D, SPOT = "#3F7FE0", "#2A5BB5", "#8FC0FF"
ORANGE, CREAM, PLUM = "#F25A12", "#FFF6EE", "#3A2647"
WATER, RIPPLE, FISH, WEED, PAPER = "#3F7FE0", "#BFD6FA", "#9C9CEB", "#2F8A74", "#FBF2EA"
_uid = itertools.count()
def svg(inner, vb="0 0 240 240"): return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}">{inner}</svg>'

def bird(eye="open", beak="closed", feet=True):
    u = next(_uid); s = []
    s.append(f'<path d="M78 168 L50 214 Q60 222 74 214 L98 178Z" fill="{BLUE_D}"/>')
    s.append(f'<ellipse cx="106" cy="152" rx="44" ry="48" transform="rotate(-18 106 152)" fill="{BLUE}"/>')
    s.append(f'<circle cx="122" cy="92" r="50" fill="{BLUE}"/>')
    s.append(f'<clipPath id="kb{u}"><ellipse cx="106" cy="152" rx="44" ry="48" transform="rotate(-18 106 152)"/></clipPath>')
    s.append(f'<circle cx="150" cy="182" r="52" fill="{ORANGE}" clip-path="url(#kb{u})"/>')
    s.append(f'<path d="M158 92 L92 104" stroke="{ORANGE}" stroke-width="22" stroke-linecap="round"/>')
    for x, y, r in [(112,58,3.5),(128,55,3.5),(100,68,3)]:
        s.append(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{SPOT}"/>')
    s.append(f'<path d="M74 132 Q114 118 130 156 Q112 194 76 182 Q62 156 74 132Z" fill="{BLUE_D}"/>')
    if beak == "open":
        s.append(f'<path d="M156 82 L224 86 L160 97 Q152 90 156 82Z" fill="{PLUM}"/>')
        s.append(f'<path d="M158 100 L216 116 L158 109Z" fill="{PLUM}"/>')
    else:
        s.append(f'<path d="M156 82 L226 98 L158 108 Q150 95 156 82Z" fill="{PLUM}"/>')
    if eye == "open":
        s.append(f'<circle cx="136" cy="95" r="7.5" fill="{PLUM}"/>')
    elif eye == "flat":   # deadpan: lid drops halfway
        s.append(f'<circle cx="136" cy="95" r="7.5" fill="{PLUM}"/>')
        s.append(f'<rect x="126" y="85" width="20" height="10" fill="{ORANGE}"/>')
        s.append(f'<path d="M128 95 H144" stroke="{PLUM}" stroke-width="3" stroke-linecap="round"/>')
    else:
        s.append(f'<path d="M129 96 Q136 101 143 96" stroke="{PLUM}" stroke-width="4" fill="none" stroke-linecap="round"/>')
    if feet:
        s.append(f'<ellipse cx="100" cy="199" rx="8" ry="5" fill="{ORANGE}"/><ellipse cx="118" cy="199" rx="8" ry="5" fill="{ORANGE}"/>')
    return "".join(s)

def sleeper():
    s = [f'<path d="M70 176 L46 210 Q58 218 70 210 L92 184Z" fill="{BLUE_D}"/>',
         f'<ellipse cx="116" cy="150" rx="62" ry="54" fill="{BLUE}"/>',
         f'<clipPath id="ks"><ellipse cx="116" cy="150" rx="62" ry="54"/></clipPath>',
         f'<circle cx="158" cy="214" r="58" fill="{ORANGE}" clip-path="url(#ks)"/>',
         f'<path d="M160 136 L110 142" stroke="{ORANGE}" stroke-width="20" stroke-linecap="round"/>']
    for x, y, r in [(116,106,3.5),(132,103,3.5)]: s.append(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{SPOT}"/>')
    s += [f'<path d="M66 140 Q104 128 122 164 Q104 196 70 188 Q56 164 66 140Z" fill="{BLUE_D}"/>',
          f'<path d="M168 134 L196 150 L170 152Z" fill="{PLUM}"/>',
          f'<path d="M136 140 Q143 145 150 140" stroke="{PLUM}" stroke-width="4" fill="none" stroke-linecap="round"/>',
          f'<ellipse cx="104" cy="200" rx="8" ry="5" fill="{ORANGE}"/><ellipse cx="124" cy="200" rx="8" ry="5" fill="{ORANGE}"/>']
    return "".join(s)

def fish(x, y, a=0, sc=1):
    return (f'<g transform="translate({x} {y}) rotate({a}) scale({sc})">'
            f'<path d="M-16 0 Q-2 -12 14 -2 L26 -10 L24 8 L14 4 Q-2 12 -16 0Z" fill="{FISH}"/>'
            f'<circle cx="-8" cy="-2" r="2.2" fill="{PLUM}"/></g>')
def ring(x, y, rx, ry, col=RIPPLE, w=4):
    return f'<ellipse cx="{x}" cy="{y}" rx="{rx}" ry="{ry}" fill="none" stroke="{col}" stroke-width="{w}"/>'
def pool(cx=120, cy=212, rx=110, ry=20): return f'<ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry}" fill="{WATER}"/>'
PERCH = f'<path d="M30 206 Q120 198 214 204" stroke="{PLUM}" stroke-width="7" stroke-linecap="round" fill="none"/>'

P = {}
P["idle"] = svg(PERCH + bird())
P["recall"] = svg(PERCH + bird() .replace('M156 82 L226 98 L158 108', 'M156 82 L222 92 L158 104') + fish(206, 96, 0, .85) +
                  f'<path d="M150 226 Q180 220 210 226" stroke="{WATER}" stroke-width="5" fill="none" stroke-linecap="round"/>' +
                  f'<path d="M166 234 Q180 231 194 234" stroke="{WATER}" stroke-width="5" fill="none" stroke-linecap="round"/>')
P["sleep"] = svg(PERCH + sleeper())

# saving: a straight dive, drawn as its own shape (the perched bird can't simply be rotated:
# its body sits beside its head, not above it). Pitched forward, so the belly faces left, the back right.
def diver():
    u = next(_uid)
    d = [f'<path d="M112 46 L100 8 Q112 2 124 8 L130 46Z" fill="{BLUE_D}"/>',                       # tail, up top
         f'<ellipse cx="118" cy="78" rx="27" ry="42" fill="{BLUE}"/>',                                # body
         f'<clipPath id="kd{u}"><ellipse cx="118" cy="78" rx="27" ry="42"/></clipPath>',
         f'<ellipse cx="90" cy="84" rx="26" ry="46" fill="{ORANGE}" clip-path="url(#kd{u})"/>',      # belly, facing left
         f'<circle cx="118" cy="128" r="31" fill="{BLUE}"/>',                                         # head
         f'<ellipse cx="136" cy="76" rx="13" ry="38" fill="{BLUE_D}"/>',                               # folded wing on the back
         f'<path d="M120 152 L112 104" stroke="{ORANGE}" stroke-width="17" stroke-linecap="round"/>', # mask band
         f'<circle cx="117" cy="134" r="6" fill="{PLUM}"/>',
         f'<circle cx="130" cy="112" r="2.8" fill="{SPOT}"/><circle cx="136" cy="124" r="2.8" fill="{SPOT}"/>',
         f'<path d="M106 154 Q118 146 130 154 L120 206Z" fill="{PLUM}"/>']                             # beak, straight down
    return "".join(d)
P["save"] = svg(pool(120, 216, 104, 18) + ring(120, 212, 26, 6) + ring(120, 212, 48, 10, RIPPLE, 3) +
                f'<g transform="translate(2 4)">{diver()}</g>' +
                "".join(f'<path d="M{x} {y} v-22" stroke="{SPOT}" stroke-width="4" stroke-linecap="round"/>' for x, y in [(82,52),(156,40),(150,74)]))

# forgetting: beak open over the water; the fish has dropped back in and swims off
P["forget"] = svg(pool(168, 212, 70, 18) +
                  f'<path d="M10 140 Q80 134 150 140" stroke="{PLUM}" stroke-width="7" stroke-linecap="round" fill="none"/>' +
                  f'<g transform="translate(2 -14) scale(.74)">{bird(beak="open")}</g>' +
                  f'<path d="M166 84 Q170 140 160 196" stroke="{SPOT}" stroke-width="3.5" stroke-dasharray="2 9" stroke-linecap="round" fill="none"/>' +
                  ring(160, 208, 20, 5) + fish(206, 214, 0, .6))

# trouble: came up with a beak full of weed, deadpan
weed = (f'<path d="M190 102 Q194 124 186 146" stroke="{WEED}" stroke-width="6" fill="none" stroke-linecap="round"/>'
        f'<path d="M204 104 Q212 128 206 154" stroke="{WEED}" stroke-width="6" fill="none" stroke-linecap="round"/>'
        f'<path d="M176 100 Q172 118 178 132" stroke="{WEED}" stroke-width="5" fill="none" stroke-linecap="round"/>'
        f'<path d="M216 98 Q228 112 224 126" stroke="{WEED}" stroke-width="5" fill="none" stroke-linecap="round"/>'
        f'<ellipse cx="206" cy="166" rx="3" ry="4.5" fill="{WATER}"/><ellipse cx="186" cy="160" rx="2.5" ry="3.5" fill="{WATER}"/>')
P["trouble"] = svg(PERCH + bird(eye="flat") + weed)

# connecting: one post per app; a post's cap turns stone-orange once it is connected; Kip ends on the last
def post(x, lit):
    return (f'<rect x="{x-9}" y="132" width="18" height="84" rx="9" fill="{PLUM}"/>' +
            f'<rect x="{x-11}" y="128" width="22" height="12" rx="6" fill="{ORANGE if lit else "#7A6A84"}"/>')
hops = "".join(f'<path d="M{a} 122 Q{(a+b)/2} 84 {b} 122" stroke="{SPOT}" stroke-width="4" stroke-dasharray="2 9" stroke-linecap="round" fill="none"/>' for a, b in [(48,120),(120,192)])
P["connect"] = svg(pool(120, 214, 112, 18) + post(48, True) + post(120, True) + post(192, False) + hops +
                   f'<g transform="translate(78 50) scale(.38)">{bird()}</g>')

if __name__ == '__main__':
    def silhouette(x):
        x = re.sub(r'fill="#[0-9A-Fa-f]{6}"', f'fill="{PLUM}"', x)
        return re.sub(r'stroke="#[0-9A-Fa-f]{6}"', f'stroke="{PLUM}"', x)
    for n, x in P.items():
        open(f"kip_{n}.svg", "w").write(x)
    open("kip_idle_sil.svg", "w").write(silhouette(P["idle"]))
    open("kip.html", "w").write('<!doctype html><meta charset="utf-8"><body style="margin:0;background:#FBF2EA;display:grid;grid-template-columns:repeat(4,200px);gap:10px;padding:16px">' +
         "".join(f'<figure style="margin:0;font:12px system-ui;text-align:center"><img src="kip_{n}.svg" width="200">{n}</figure>' for n in P))
    print("ok")
