"""Logo dosyalarını üretir: işaret (İbre) ve ad (Jost Medium, aralıklı büyük harf).

Kullanım: python3 tools/logo.py  ->  marka/*.svg, marka/*.png ve web/yazi.json
Gerekli paketler (yalnızca bu betik için): fonttools, pymupdf.

Ad, yazı tipine bağımlı kalmasın diye harf çizgilerine (vektör yol) çevrilir; sitede ve baskıda yazı tipi
yüklenmeden aynı görünür. Yazı tipi: Jost (SIL Open Font License), marka/kaynak/ altında.
"""

import json
from pathlib import Path

import fitz
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "marka"
NAME, WEIGHT, TRACKING = "İHRAÇBUL", 500, 0.16          # harf aralığı em cinsinden
RED, INK, PAPER = "#e30a17", "#0b0c0f", "#ffffff"
MARK = ('<circle cx="16" cy="16" r="9" fill="none" stroke="{c}" stroke-width="2.4"/>'
        '<path d="M16 16 22.5 9.5" fill="none" stroke="{c}" stroke-width="2.6" stroke-linecap="round"/>'
        '<circle cx="16" cy="16" r="2.2" fill="{c}"/>')


def wordmark():
    """Adın yolu ve ölçüleri: (d, genişlik, büyük harf yüksekliği, üst taşma, alt taşma), yazı tipi biriminde; y aşağı doğru."""
    font = instantiateVariableFont(TTFont(OUT / "kaynak" / "Jost.ttf"), {"wght": WEIGHT})
    glyphs, cmap, upm = font.getGlyphSet(), font.getBestCmap(), font["head"].unitsPerEm
    cap = font["OS/2"].sCapHeight
    path, bounds, x = SVGPathPen(glyphs), BoundsPen(glyphs), 0
    for index, char in enumerate(NAME):
        name = cmap[ord(char)]
        for pen in (path, bounds):
            glyphs[name].draw(TransformPen(pen, (1, 0, 0, -1, x, cap)))      # y ekseni çevrilir, büyük harf tepesi y=0
        x += glyphs[name].width + (TRACKING * upm if index < len(NAME) - 1 else 0)
    x_min, y_min, x_max, y_max = bounds.bounds
    return path.getCommands(), x_min, x_max, cap, -y_min, y_max - cap


def build():
    d, x_min, x_max, cap, over, under = wordmark()
    pad = max(over, under)                    # üstte İ'nin noktası, altta Ç'nin çengeli: kutu büyük harflere göre ortalı kalsın
    width, height = x_max - x_min, cap + 2 * pad
    box = f"{x_min:.0f} {-pad:.0f} {width:.0f} {height:.0f}"
    (ROOT / "web" / "yazi.json").write_text(json.dumps({"viewBox": box, "d": d, "oran": round(width / height, 4)}))

    def svg(view, body, w, h):
        return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{view}" width="{w}" height="{h}" role="img" aria-label="İhraçbul">{body}</svg>'

    files = {"yazi-koyu-zemin.svg": svg(box, f'<path d="{d}" fill="{PAPER}"/>', round(width / height * 120), 120),
             "yazi-acik-zemin.svg": svg(box, f'<path d="{d}" fill="{INK}"/>', round(width / height * 120), 120),
             "isaret.svg": svg("0 0 32 32", f'<rect width="32" height="32" rx="7" fill="{RED}"/>' + MARK.format(c=PAPER), 512, 512),
             "isaret-kirmizi-zemin.svg": svg("0 0 32 32", f'<rect width="32" height="32" rx="7" fill="{PAPER}"/>' + MARK.format(c=RED), 512, 512)}
    # Yatay logo: 32 birimlik karo, 13 birim boşluk, ad büyük harf yüksekliği 12,4 birim olacak biçimde ölçeklenir.
    scale = 12.4 / cap
    name_w = width * scale
    total = 32 + 13 + name_w
    for label, tile, glyph, ink in (("koyu-zemin", RED, PAPER, PAPER), ("acik-zemin", RED, PAPER, INK), ("kirmizi-zemin", PAPER, RED, PAPER)):
        body = (f'<rect width="32" height="32" rx="7" fill="{tile}"/>' + MARK.format(c=glyph)
                + f'<path transform="translate({45 - x_min * scale:.2f} {16 - cap * scale / 2:.2f}) scale({scale:.5f})" d="{d}" fill="{ink}"/>')
        files[f"logo-{label}.svg"] = svg(f"0 0 {total:.1f} 32", body, round(total * 8), 256)
    files["profil.svg"] = svg("0 0 32 32", f'<rect width="32" height="32" fill="{RED}"/><g transform="translate(5.6 5.6) scale(.65)">' + MARK.format(c=PAPER) + "</g>", 1024, 1024)
    for name, content in files.items():
        (OUT / name).write_text(content, encoding="utf-8")
        page = fitz.open(stream=content.encode("utf-8"), filetype="svg")[0]
        zoom = 2048 / max(page.rect.width, page.rect.height)
        page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=name != "profil.svg").save(OUT / name.replace(".svg", ".png"))
    return sorted(files), box, round(width / height, 3)


if __name__ == "__main__":
    names, box, ratio = build()
    print(f"{len(names)} SVG ve PNG yazıldı: {OUT}")
    print("ad kutusu:", box, "| en/boy:", ratio)
