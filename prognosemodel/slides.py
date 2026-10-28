"""Prognosedeckets slides som redigerbare PowerPoint-objekter på PPIM-masteren.

Byggeklodserne (talformater, _tabel, Fodnoter, _diagramakser, _linjeplot, sidefod, ...) er
taget fra pe-fund-report/pe_fund_report/slides.py, så decket ligner porteføljerapporten.
Hver slide-funktion tager præsentationen, investorens data (data.hent) og prognosen
(beregning.prognose) og returnerer sliden, eller None, hvis der ikke er noget at vise.
"""
import uuid
from copy import deepcopy

from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION
from pptx.enum.chart import XL_MARKER_STYLE, XL_TICK_LABEL_POSITION
from pptx.enum.dml import MSO_LINE_DASH_STYLE
from pptx.enum.shapes import MSO_SHAPE, PP_PLACEHOLDER
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml import parse_xml
from pptx.oxml.ns import nsdecls, qn
from pptx.util import Inches, Pt

from . import style
from .beregning import kommende
from .deck import BROED_FONT, L_TEKST, _fjern_tomme_ph, _ny_slide, _saet_ph
from .noegletal import deling, kaedet, kvartalsafkast

IKKE_OPLYST = "n/a"
INGEN_TABELSTIL = "{2D5ABB26-0587-4C30-8999-92F81FD0307C}"   # "No Style, No Grid"

# Indholdsfladen på Layout_basic_2 (tommer)
X0, X1 = 0.66, 11.04
Y_UNDERTITEL, Y_TOP, Y_NOTER = 0.86, 1.22, 5.90
FLISE_Y, FLISE_H = 1.12, 0.62
KURVE_Y = 1.88

V, H, C = PP_ALIGN.LEFT, PP_ALIGN.RIGHT, PP_ALIGN.CENTER
KILDE = "Kilde: P&P's fondsregnskaber og transaktioner, Danmarks Nationalbank og egne beregninger."


def _rgb(hexfarve):
    return RGBColor.from_string(hexfarve.lstrip("#"))


SAGE, SAGE_LYS, CREAM = _rgb(style.PPIM_SAGE_DARK), _rgb(style.PPIM_SAGE_LIGHT), _rgb(style.PPIM_CREAM)
SORT, HVID, STREG = _rgb(style.PPIM_BLACK), _rgb(style.PPIM_WHITE), _rgb(style.LINE)
SAGE_MID, TERRA, TAUPE = _rgb(style.PPIM_SAGE_MID), _rgb(style.PPIM_TERRACOTTA), _rgb(style.PPIM_TAUPE_LIGHT)
OLIVEN, ROED, BRUN = _rgb(style.PPIM_OLIVE), _rgb(style.PPIM_RED_MUTED), _rgb(style.PPIM_BROWN)
LYSE = {SAGE_LYS, TAUPE, CREAM, _rgb(style.PPIM_BEIGE)}

# fondenes faste farver; samme rækkefølge som data.FONDSORDEN
FOND_FARVER = [SAGE, TERRA, TAUPE, OLIVEN, SAGE_LYS, BRUN]
SCENARIEFARVER = {"basis": SORT, "svag": ROED, "staerk": OLIVEN}


# ---------- talformater (dansk) ----------

def beloeb(v):
    """Et beløb i mio. med én decimal: 54,4."""
    return IKKE_OPLYST if v is None else style._dk(v / 1_000_000, 1)


def _mio(v):
    return round((v or 0.0) / 1_000_000, 2)


def pct(v, dec=1):
    """v er en andel (0,123 -> 12,3 %)."""
    return IKKE_OPLYST if v is None else style._dk(v * 100, dec) + " %"


def gange(v):
    return IKKE_OPLYST if v is None else style.mult(v)


def kvartal(d):
    return f"Q{(d.month - 1) // 3 + 1} {d:%y}"


# ---------- byggeklodser ----------

def _skriv(tf, tekst, pt, fed=False, farve=SORT, just=V, kursiv=False):
    """Skriv tekst i første afsnit; "\n" giver et linjeskift i samme afsnit."""
    para = tf.paragraphs[0]
    para.alignment = just
    for i, linje in enumerate(str(tekst).split("\n")):
        if i:
            para._p.add_br().get_or_add_rPr().set("sz", str(round(pt * 100)))
        run = para.add_run()
        run.text = linje
        run.font.name, run.font.size = BROED_FONT, Pt(pt)
        run.font.bold, run.font.italic = fed, kursiv
        run.font.color.rgb = farve
    return para


def _tekst(slide, x, y, w, h, tekst, pt, fed=False, farve=SORT, just=V, kursiv=False,
           anker=MSO_ANCHOR.TOP):
    tf = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h)).text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anker
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    _skriv(tf, tekst, pt, fed, farve, just, kursiv)
    return tf


def _punkter(slide, x, y, w, h, punkter, pt=10):
    """En tekstboks med ét afsnit pr. punkt; et punkt (overskrift, tekst) får fed overskrift."""
    tf = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h)).text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    for i, p in enumerate(punkter):
        para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        para.space_after = Pt(5)
        overskrift, tekst = p if isinstance(p, tuple) else (None, p)
        if overskrift:
            r = para.add_run()
            r.text = overskrift + " "
            r.font.name, r.font.size, r.font.bold = BROED_FONT, Pt(pt), True
            r.font.color.rgb = SAGE
        r = para.add_run()
        r.text = tekst
        r.font.name, r.font.size = BROED_FONT, Pt(pt)
        r.font.color.rgb = SORT
    return tf


def _titel(slide, tekst):
    """Titel uden masterens venstre-indryk, så den flugter med undertitel og indhold."""
    ph = _saet_ph(slide, 0, tekst)
    ph.text_frame.margin_left = 0
    return ph


def _streg(slide, x1, y1, x2, y2, farve=SAGE, pt=0.75, stiplet=False):
    s = slide.shapes.add_connector(1, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
    s.line.color.rgb = farve
    s.line.width = Pt(pt)
    if stiplet:
        s.line.dash_style = MSO_LINE_DASH_STYLE.DASH
    return s


def _bjaelke(slide, x, y, w, h, farve):
    f = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(max(w, 0.004)),
                               Inches(max(h, 0.004)))
    f.fill.solid()
    f.fill.fore_color.rgb = farve
    f.line.fill.background()
    f.shadow.inherit = False
    f.text_frame.text = ""
    return f


def _fliser(slide, fliser, y=FLISE_Y, h=FLISE_H, luft=0.10):
    """Nøgletalsfliser i lige brede felter: [(label, værdi)], stort tal over en label."""
    n = len(fliser)
    w = (X1 - X0 - luft * (n - 1)) / n
    for i, (label, tal) in enumerate(fliser):
        x = X0 + i * (w + luft)
        _bjaelke(slide, x, y, w, h, CREAM)
        _tekst(slide, x, y, w, h * 0.58, str(tal), 16, fed=True, farve=SAGE, just=C,
               anker=MSO_ANCHOR.BOTTOM)
        _tekst(slide, x, y + h * 0.62, w, h * 0.35, label, 8, just=C)


def _tabel(slide, x, y, w, raekker, bredder, just, raekke_h, pt, hoved=False, total=False,
           zebra=False, totaler=()):
    """Tabel uden PowerPoints tabelstil. raekker er lister af færdigformaterede tekster."""
    gf = slide.shapes.add_table(len(raekker), len(bredder), Inches(x), Inches(y),
                                Inches(w), Inches(raekke_h * len(raekker)))
    tbl = gf.table
    tbl.first_row = tbl.horz_banding = False
    tbl._tbl.tblPr.find(qn("a:tableStyleId")).text = INGEN_TABELSTIL
    for j, b in enumerate(bredder):
        tbl.columns[j].width = Inches(w * b / sum(bredder))
    sidste = len(raekker) - 1
    for i, raekke in enumerate(raekker):
        tbl.rows[i].height = Inches(raekke_h)
        er_hoved = hoved and i == 0
        er_total = (total and i == sidste) or i in totaler
        for j, vaerdi in enumerate(raekke):
            celle = tbl.cell(i, j)
            celle.margin_left = celle.margin_right = Inches(0.05)
            celle.margin_top = celle.margin_bottom = Inches(0.01)
            celle.vertical_anchor = MSO_ANCHOR.MIDDLE
            if er_hoved:
                celle.fill.solid()
                celle.fill.fore_color.rgb = SAGE
            elif er_total:
                celle.fill.solid()
                celle.fill.fore_color.rgb = SAGE_LYS
            elif zebra and (i - hoved) % 2 == 1:
                celle.fill.solid()
                celle.fill.fore_color.rgb = CREAM
            else:
                celle.fill.background()
            para = _skriv(celle.text_frame, vaerdi, pt, fed=er_hoved or er_total,
                          farve=HVID if er_hoved else SORT, just=just[j])
            para._p.get_or_add_endParaRPr().set("sz", str(round(pt * 100)))
    return tbl


NOTE_TEGN, NOTE_LINJE, NOTE_BUND = 200, 0.118, 6.28
SUPERSKRIFT = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")


def _noter_y(tekst, y=Y_NOTER):
    return min(y, NOTE_BUND - (len(tekst) // NOTE_TEGN + 1) * NOTE_LINJE)


class Fodnoter:
    """Noterne nederst på én slide: generelle noter og nummererede fodnoter (¹, ², ...)."""

    def __init__(self, kilde=KILDE):
        self.generelle = []
        self.numre = {}
        self.generel(kilde)

    def maerke(self, tekst):
        if not tekst:
            return ""
        return str(self.numre.setdefault(tekst, len(self.numre) + 1)).translate(SUPERSKRIFT)

    def generel(self, *tekster):
        for t in tekster:
            if t and t not in self.generelle:
                self.generelle.append(t)

    def tekst(self):
        nummererede = [f"{str(nr).translate(SUPERSKRIFT)} {t}"
                       for t, nr in sorted(self.numre.items(), key=lambda x: x[1])]
        return " ".join(self.generelle + nummererede)

    def y(self):
        return _noter_y(self.tekst())

    def tegn(self, s):
        tekst = self.tekst()
        if tekst:
            _tekst(s, X0, self.y(), X1 - X0, 0.5, tekst, 7, kursiv=True)


def _diagramakser(diagram, talformat):
    """Vandrette gitterlinjer, ingen lodret akselinje, kategorierne nederst."""
    diagram.font.name, diagram.font.size = BROED_FONT, Pt(8)
    diagram.font.color.rgb = SORT
    y_akse, x_akse = diagram.value_axis, diagram.category_axis
    y_akse.has_major_gridlines = True
    y_akse.major_gridlines.format.line.color.rgb = _rgb(style.GRID)
    y_akse.major_gridlines.format.line.width = Pt(0.75)
    y_akse.format.line.fill.background()
    y_akse.tick_labels.number_format, y_akse.tick_labels.number_format_is_linked = talformat, False
    x_akse.format.line.color.rgb = STREG
    x_akse.has_major_gridlines = False
    x_akse.tick_label_position = XL_TICK_LABEL_POSITION.LOW
    diagram.has_legend = True
    diagram.legend.position = XL_LEGEND_POSITION.BOTTOM
    diagram.legend.include_in_layout = False
    diagram.legend.font.size = Pt(8)


def _farv(serie, farve):
    serie.format.fill.solid()
    serie.format.fill.fore_color.rgb = farve


def _linjeplot(diagram, bar, ser, farve, nr, i_forklaring=True, stiplet=False):
    """Gør søjleserien ser (taget ud af søjlediagrammet bar) til en linje på samme akser,
    tegnet foran søjlerne: python-pptx kan ikke bygge kombinationsdiagrammer."""
    for tag in ("c:invertIfNegative", "c:spPr", "c:dLbls"):
        for el in ser.findall(qn(tag)):
            ser.remove(el)
    ser.find(qn("c:idx")).set("val", str(nr))
    ser.find(qn("c:order")).set("val", str(nr))
    ser.find(qn("c:tx")).addnext(parse_xml(
        f'<c:spPr {nsdecls("c", "a")}><a:ln w="22225" cap="rnd"><a:solidFill>'
        f'<a:srgbClr val="{farve}"/></a:solidFill>'
        + ('<a:prstDash val="dash"/>' if stiplet else '') + '<a:round/></a:ln></c:spPr>'))
    ser.find(qn("c:spPr")).addnext(parse_xml(
        f'<c:marker {nsdecls("c")}><c:symbol val="none"/></c:marker>'))
    ser.append(parse_xml(f'<c:smooth {nsdecls("c")} val="0"/>'))
    plot = parse_xml(f'<c:lineChart {nsdecls("c")}><c:grouping val="standard"/>'
                     f'<c:varyColors val="0"/></c:lineChart>')
    plot.append(ser)
    for akse in bar.findall(qn("c:axId")):
        plot.append(deepcopy(akse))
    bar.addnext(plot)
    if not i_forklaring and diagram.has_legend:
        diagram.legend._element.find(qn("c:legendPos")).addnext(parse_xml(
            f'<c:legendEntry {nsdecls("c")}><c:idx val="{nr}"/>'
            f'<c:delete val="1"/></c:legendEntry>'))
    return plot


def _skjul_i_forklaring(diagram, idx):
    diagram.legend._element.find(qn("c:legendPos")).addnext(parse_xml(
        f'<c:legendEntry {nsdecls("c")}><c:idx val="{idx}"/><c:delete val="1"/></c:legendEntry>'))


def _kombi(s, x, y, w, h, kategorier, soejler, linjer, talformat='#,##0" mio."',
           stablet=True):
    """Søjler (evt. stablede) med linjer foran: soejler = [(navn, værdier, farve, i_forklaring)],
    linjer = [(navn, værdier, farve, stiplet)]."""
    cd = CategoryChartData(number_format="#,##0.0")
    cd.categories = kategorier
    for navn, vaerdier, *_ in soejler + linjer:
        cd.add_series(navn, vaerdier)
    typ = XL_CHART_TYPE.COLUMN_STACKED if stablet else XL_CHART_TYPE.COLUMN_CLUSTERED
    diagram = s.shapes.add_chart(typ, Inches(x), Inches(y), Inches(w), Inches(h), cd).chart
    _diagramakser(diagram, talformat)
    plot = diagram.plots[0]
    plot.gap_width = 55
    if stablet:
        plot.overlap = 100
    for serie, (_, _, farve, _) in zip(plot.series, soejler):
        _farv(serie, farve)
        serie.invert_if_negative = False
    bar = plot._element
    sers = bar.findall(qn("c:ser"))[len(soejler):]
    for i, (ser, (_, _, farve, stiplet)) in reversed(list(enumerate(zip(sers, linjer)))):
        bar.remove(ser)
        _linjeplot(diagram, bar, ser, farve, len(soejler) + i, stiplet=stiplet)
    for i, (*_, med) in reversed(list(enumerate(soejler))):
        if not med:
            _skjul_i_forklaring(diagram, i)
    return diagram


def _linjediagram(s, x, y, w, h, kategorier, serier, talformat):
    """Linjer: serier = [(navn, værdier, farve, stiplet)]."""
    cd = CategoryChartData(number_format="#,##0.00")
    cd.categories = kategorier
    for navn, vaerdier, *_ in serier:
        cd.add_series(navn, vaerdier)
    diagram = s.shapes.add_chart(XL_CHART_TYPE.LINE, Inches(x), Inches(y), Inches(w), Inches(h),
                                 cd).chart
    _diagramakser(diagram, talformat)
    for serie, (_, _, farve, stiplet) in zip(diagram.plots[0].series, serier):
        serie.format.line.color.rgb = farve
        serie.format.line.width = Pt(1.75)
        serie.smooth = False
        serie.marker.style = XL_MARKER_STYLE.NONE
        if stiplet:
            serie.format.line.dash_style = MSO_LINE_DASH_STYLE.DASH
    return diagram


def _etiketter(serie, tekster, farve=SORT, position=XL_LABEL_POSITION.OUTSIDE_END):
    for punkt, tekst in zip(serie.points, tekster):
        if not tekst:
            continue
        e = punkt.data_label
        e.position = position
        e.text_frame.text = tekst
        run = e.text_frame.paragraphs[0].runs[0]
        run.font.size, run.font.color.rgb = Pt(7.5), farve


# ---------- fælles ----------

def _slide(prs, r, titel, enhed):
    s = _ny_slide(prs, L_TEKST)
    _titel(s, titel)
    _fjern_tomme_ph(s)
    _tekst(s, X0, Y_UNDERTITEL, X1 - X0, 0.22,
           f"{r['navn']}  ·  pr. {r['dato']:%d.%m.%Y}" + (f"  ·  {enhed}" if enhed else ""), 9.5)
    return s


def _farver(r):
    return {f["fond"]: FOND_FARVER[i % len(FOND_FARVER)] for i, f in enumerate(r["fonde"])}


def _kursnote(r):
    return ("Dagskurser (Nationalbanken): " + ", ".join(
        f"{v} {style._dk(k['kurs'], 4)} ({k['dato']:%d.%m.%Y})"
        for v, k in sorted(r["kurser"].items())) + ".")


def _aar_label(a, r):
    return f"{a['aar']}P" if a["aar"] > r["dato"].year else (
        f"{a['aar']}*" if a["aar"] == r["dato"].year else str(a["aar"]))


def _aar_note(r):
    aar = r["dato"].year
    return (f"P = prognose. {aar}* er faktiske tal til og med {r['dato']:%d.%m.%Y} plus "
            "prognose for resten af året.")


def _motor_note(p):
    if p["motor"] == "excel":
        return ("Prognosen følger metoden fra det tidligere Excel-ark: kald = RC x tilsagn, "
                "udlodning = RD x NAV året før, NAV vokser med P&P's forventede afkast.")
    return (f"Prognosen er en Takahashi-Alexander-model (scenarie: {p['scenarie_navn']}): "
            "kald som andel af resttilsagnet, udlodninger stigende med fondens alder, NAV "
            "vokser med P&P's forventede afkast. Se forudsætningerne i bilaget.")


def _handel_note(r):
    """Note, når investoren har købt eller solgt andele af andre investorer."""
    if any(b[3] in ("KØB", "SALG") for f in [*r["fonde"], *r.get("solgte", [])]
           for b in f["betalinger"]):
        return ("Køb og salg af andele fra/til andre investorer indgår som ind- og udbetalinger "
                "til den aftalte pris.")
    return None


def _vaerdi_note(r):
    return (f"Markedsværdi = seneste NAV (fondsregnskab pr. {r['total']['seneste_nav_dato']:%d.%m.%Y}) "
            "+ ind- og udbetalinger siden, omregnet til dagskurs.")


# ---------- slides ----------

def sammendrag(prs, r, p):
    """Nøgletallene for hele porteføljen og udviklingen i NAV og likviditet over tid."""
    t = r["total"]
    s = _slide(prs, r, "Sammendrag", "hele porteføljen, beløb i mio. DKK")
    fod = Fodnoter()
    irr_m = fod.maerke("IRR i DKK fra første indbetaling til i dag med markedsværdien som "
                       "slutværdi.")
    fod.generel(_vaerdi_note(r), _aar_note(r), _motor_note(p), _handel_note(r))
    from .data import portefoelje_irr
    _fliser(s, [("Tilsagn", beloeb(t["tilsagn_dkk"])),
                ("Indbetalt", beloeb(t["betalt_dkk"])),
                ("Resttilsagn", beloeb(t["resttilsagn_dkk"])),
                ("Udloddet", beloeb(t["udloddet_dkk"])),
                ("Markedsværdi", beloeb(t["markedsvaerdi_dkk"])),
                ("TVPI", gange(t["tvpi"])),
                ("IRR" + irr_m, pct(portefoelje_irr(r)))])
    linjer = p["total"]
    kat = [_aar_label(a, r) for a in linjer]
    y = KURVE_Y + 0.05
    _tekst(s, X0, y, X1 - X0, 0.22, "NAV ved årets udgang og akkumuleret likviditet", 11,
           fed=True)
    _kombi(s, X0, y + 0.24, X1 - X0, fod.y() - 0.08 - y - 0.24, kat,
           [("NAV", [_mio(a["nav"]) for a in linjer], SAGE, True)],
           [("Akkumuleret likviditet (udlodninger - indbetalinger)",
             [_mio(a["kum_likviditet"]) for a in linjer], TERRA, False),
            ("Akkumuleret afkast (likviditet + NAV)",
             [_mio(a["afkast_akk"]) for a in linjer], SORT, True)], stablet=False)
    fod.tegn(s)
    return s


def portefoelje(prs, r, p):
    """Én række pr. fond: tilsagn, indbetalt, NAV, markedsværdi, afkast og prognosens TVPI."""
    s = _slide(prs, r, "Porteføljen pr. fond", "beløb i mio.")
    fod = Fodnoter()
    v_m = fod.maerke("Tilsagn, indbetalt og NAV i fondens valuta.")
    irr_m = fod.maerke("IRR fra første indbetaling til i dag med markedsværdien som slutværdi; "
                       "i DKK inkl. valutakursudviklingen.")
    kv_m = fod.maerke("Seneste kvartal med NAV for alle fonde; i DKK.")
    pr_m = fod.maerke(f"TVPI i DKK ved prognosens udgang ({p['slut_aar']}).")
    fod.generel(_vaerdi_note(r), _kursnote(r), _handel_note(r))
    if r.get("solgte"):
        fod.generel("Solgte positioner (" + ", ".join(x["fond"] for x in r["solgte"])
                    + ") indgår kun i porteføljens indbetalt, udloddet og IRR.")
    ks = [f["fond"] for f in r["fonde"] if f.get("ejerandel_grundlag") == "indbetalt"]
    ks_m = fod.maerke(f"{', '.join(ks)} er et K/S uden aktier; ejerandelen er investorens andel "
                      "af fondens samlede indbetalinger.") if ks else ""
    kv = kvartalstal(r)
    hoved = ["Fond", "Valuta", "Vintage", "Tilsagn" + v_m, "Indbetalt" + v_m, "Indbetalt %",
             "NAV-dato", "NAV" + v_m, "Markedsværdi DKK", "IRR valuta" + irr_m, "IRR DKK" + irr_m,
             "TVPI DKK", "Seneste kvartal" + kv_m, "TVPI prognose" + pr_m]
    raekker = [hoved]
    for f in r["fonde"]:
        sidste = kv["seneste"].get(f["fond"])
        mk = ks_m if f["fond"] in ks else ""
        raekker.append([f"{f['fond']}{mk}\n{f['underliggende_fond'] or ''}", f["valuta"],
                        str(f["vintage"]), beloeb(f["tilsagn"]), beloeb(f["indbetalt"]),
                        pct(f["indbetalt_pct"], 0),
                        f"{f['nav_dato']:%d.%m.%Y}" if f["nav_dato"] else IKKE_OPLYST,
                        beloeb(f["nav_valuta"]), beloeb(f["markedsvaerdi_dkk"]),
                        pct(f["irr_valuta"]), pct(f["irr_dkk"]),
                        gange(f["multipler_dkk"]["tvpi"]), pct(sidste),
                        gange(p["fonde"][f["fond"]]["tvpi"])])
    t = r["total"]
    from .data import portefoelje_irr
    raekker.append(["I alt (DKK)", "DKK", "", beloeb(t["tilsagn_dkk"]), beloeb(t["betalt_dkk"]),
                    pct(t["indbetalt_pct"], 0), "", beloeb(t["nav_dkk"]),
                    beloeb(t["markedsvaerdi_dkk"]), "", pct(portefoelje_irr(r)),
                    gange(t["tvpi"]), pct(kv["seneste"].get("I alt")),
                    gange(_total_tvpi(p))])
    raekke_h = min(0.46, (fod.y() - Y_TOP - 0.15) / len(raekker))
    _tabel(s, X0, Y_TOP, X1 - X0, raekker,
           bredder=[2.3, 0.55, 0.6, 0.75, 0.8, 0.75, 0.85, 0.75, 1.0, 0.75, 0.75, 0.7, 0.85, 0.85],
           just=[V, C, C] + [H] * 11, raekke_h=raekke_h, pt=8, hoved=True, total=True,
           zebra=True)
    fod.tegn(s)
    return s


def _total_tvpi(p):
    t = p["total"]
    return deling(t[-1]["kum_udlodning"] + t[-1]["nav"], t[-1]["kum_kald"])


def kvartalstal(r):
    """Kvartalsafkast pr. fond i indeværende år (som arket Kvartalsafkast).

    dict(kvartaler=[datoer], fonde={fond: {dkk: [...], valuta: [...]}}, total=[...],
    aatd={fond: (dkk, valuta)}, seneste={fond: afkast})."""
    datoer = [k["dato"] for k in r["fonde"][0]["kvartaler"]][1:] if r["fonde"] else []
    fonde, total_beloeb, total_primo = {}, {}, {}
    for f in r["fonde"]:
        nav_d = {k["dato"]: k["nav_dkk"] for k in f["kvartaler"]}
        nav_v = {k["dato"]: k["nav_valuta"] for k in f["kvartaler"]}
        netto_d = {k["dato"]: k["netto_dkk"] for k in f["kvartaler"]}
        netto_v = {k["dato"]: k["netto_valuta"] for k in f["kvartaler"]}
        dkk = {x["dato"]: x for x in kvartalsafkast(nav_d, netto_d) if x["primo"]}
        val = {x["dato"]: x for x in kvartalsafkast(nav_v, netto_v) if x["primo"]}
        fonde[f["fond"]] = dict(dkk=[dkk[d]["afkast"] if d in dkk else None for d in datoer],
                                valuta=[val[d]["afkast"] if d in val else None for d in datoer])
        for d, x in dkk.items():
            total_beloeb[d] = total_beloeb.get(d, 0.0) + x["afkast_beloeb"]
            total_primo[d] = total_primo.get(d, 0.0) + x["primo"]
    total = [deling(total_beloeb[d], total_primo[d]) if d in total_beloeb else None
             for d in datoer]
    seneste_i = max((i for i, v in enumerate(total) if v is not None), default=None)
    seneste = {}
    if seneste_i is not None:
        seneste = {f: v["dkk"][seneste_i] for f, v in fonde.items()}
        seneste["I alt"] = total[seneste_i]
    return dict(kvartaler=datoer, fonde=fonde, total=total, seneste=seneste,
                seneste_dato=datoer[seneste_i] if seneste_i is not None else None)


def kvartalsafkast_slide(prs, r, p):
    """Afkastet pr. kvartal i indeværende år, i DKK og i fondens valuta, med ÅTD."""
    kv = kvartalstal(r)
    if not kv["kvartaler"] or kv["seneste_dato"] is None:
        return None
    aar = r["dato"].year
    s = _slide(prs, r, f"Afkast pr. kvartal {aar}", "afkast i procent")
    fod = Fodnoter()
    fod.generel("Afkast = (NAV ultimo - NAV primo + udlodninger - indbetalinger) / NAV primo. "
                "Kvartalerne er kædet geometrisk til år til dato (ÅTD).",
                "Kvartaler uden NAV fra fondsregnskabet vises som n/a.",
                "I alt (DKK) er vægtet med fondenes NAV primo.")
    hoved = ["Fond"] + [kvartal(d) for d in kv["kvartaler"]] + ["ÅTD"]
    blokke = []
    for overskrift, noegle in (("I DKK", "dkk"), ("I fondens valuta", "valuta")):
        raekker = [hoved]
        for f in r["fonde"]:
            v = kv["fonde"][f["fond"]][noegle]
            raekker.append([f"{f['fond']} ({f['valuta']})" if noegle == "valuta" else f["fond"]]
                           + [pct(x) for x in v] + [pct(kaedet(v))])
        if noegle == "dkk":
            raekker.append(["I alt (DKK)"] + [pct(x) for x in kv["total"]]
                           + [pct(kaedet(kv["total"]))])
        blokke.append((overskrift, raekker, noegle == "dkk"))
    w = (X1 - X0 - 0.4) / 2
    for i, (overskrift, raekker, total) in enumerate(blokke):
        x = X0 + i * (w + 0.4)
        _tekst(s, x, Y_TOP, w, 0.22, overskrift, 10.5, fed=True, farve=SAGE)
        _streg(s, x, Y_TOP + 0.26, x + w, Y_TOP + 0.26)
        _tabel(s, x, Y_TOP + 0.36, w, raekker, bredder=[2.0] + [0.8] * (len(hoved) - 1),
               just=[V] + [H] * (len(hoved) - 1), raekke_h=0.30, pt=8.5, hoved=True,
               total=total, zebra=True)
    # afkastet i DKK pr. kvartal som søjler pr. fond under tabellerne
    med = [i for i, v in enumerate(kv["total"]) if v is not None]
    y = Y_TOP + 0.36 + 0.30 * (len(r["fonde"]) + 2) + 0.3
    hoejde = fod.y() - 0.08 - y - 0.24
    if med and hoejde > 1.2:
        _tekst(s, X0, y, X1 - X0, 0.22, "Afkast i DKK pr. kvartal", 11, fed=True)
        farver = _farver(r)
        soejler = [(f, [round((kv["fonde"][f]["dkk"][i] or 0) * 100, 4) for i in med],
                    farver[f], True) for f in kv["fonde"]]
        soejler.append(("I alt (DKK)", [round(kv["total"][i] * 100, 4) for i in med], SORT, True))
        d = _kombi(s, X0, y + 0.24, X1 - X0, hoejde, [kvartal(kv["kvartaler"][i]) for i in med],
                   soejler, [], talformat='0.0" %"', stablet=False)
        d.plots[0].gap_width = 80
        for serie in d.plots[0].series:
            _etiketter(serie, [pct(v / 100) for v in serie.values])
    fod.tegn(s)
    return s


def likviditetsprognose(prs, r, p):
    """Kald (under nul) og udlodninger (over) pr. år, stablet pr. fond, med årets netto som
    linje og de andre scenariers netto stiplet."""
    aar0 = r["dato"].year
    s = _slide(prs, r, "Forventede kapitalkald og udlodninger", "prognose, beløb i mio. DKK")
    fod = Fodnoter()
    fod.generel(_aar_note(r), _motor_note(p),
                "Beløb i fremmed valuta er omregnet med dagskursen, også for de kommende år.",
                _handel_note(r))
    farver = _farver(r)
    k = {f: kommende(res["linjer"], aar0, 3) for f, res in p["fonde"].items()}
    sum_ = lambda felt: sum(a[felt] for x in k.values() for a in x)
    rest = sum(x[0]["kald"] for x in k.values() if x)
    _fliser(s, [(f"Kald resten af {aar0}", beloeb(rest)),
                (f"Kald {aar0}-{aar0 + 2}", beloeb(sum_("kald"))),
                (f"Udlodninger {aar0}-{aar0 + 2}", beloeb(sum_("udlodning"))),
                (f"Netto {aar0}-{aar0 + 2}", beloeb(sum_("netto"))),
                ("Resttilsagn i dag", beloeb(r["total"]["resttilsagn_dkk"]))])
    linjer = [a for a in p["total"] if a["aar"] >= aar0 - 2]
    kat = [_aar_label(a, r) for a in linjer]
    soejler = []
    for f, res in p["fonde"].items():
        aar = {a["aar"]: a for a in res["linjer"]}
        soejler.append((f, [-_mio(aar.get(a["aar"], {}).get("kald", 0)) for a in linjer],
                        farver[f], True))
    for f, res in p["fonde"].items():
        aar = {a["aar"]: a for a in res["linjer"]}
        soejler.append((f, [_mio(aar.get(a["aar"], {}).get("udlodning", 0)) for a in linjer],
                        farver[f], False))
    netto = [("Netto, " + (p["scenarie_navn"] or p["motor"]).lower(),
              [_mio(a["netto"]) for a in linjer], SORT, False)]
    for noegle, total in (p.get("scenarier") or {}).items():
        if noegle == p["scenarie"]:
            continue
        aar = {a["aar"]: a for a in total}
        netto.append((f"Netto, {_scenarienavn(p, noegle).lower()}",
                      [_mio(aar[a["aar"]]["netto"]) if a["aar"] in aar else None for a in linjer],
                      SCENARIEFARVER.get(noegle, ROED), True))
    y = KURVE_Y + 0.05
    _tekst(s, X0, y, X1 - X0, 0.22, "Kapitalkald (under nul) og udlodninger (over nul) pr. år",
           11, fed=True)
    _kombi(s, X0, y + 0.24, X1 - X0, fod.y() - 0.08 - y - 0.24, kat, soejler, netto)
    fod.tegn(s)
    return s


def _scenarienavn(p, noegle):
    return {"basis": "Basis", "svag": "Svagt marked", "staerk": "Stærkt marked"}.get(noegle, noegle)


def nav_prognose(prs, r, p):
    """NAV ved årets udgang stablet pr. fond (faktisk og prognose) og den akkumulerede
    likviditet i hvert scenarie."""
    s = _slide(prs, r, "Forventet NAV og likviditet", "prognose, beløb i mio. DKK")
    fod = Fodnoter()
    fod.generel(_aar_note(r), _motor_note(p),
                "Akkumuleret likviditet = alle udlodninger - alle indbetalinger fra start.")
    farver = _farver(r)
    linjer = p["total"]
    kat = [_aar_label(a, r) for a in linjer]
    aar0 = r["dato"].year
    fem = next((a for a in linjer if a["aar"] == aar0 + 4), linjer[-1])
    nul = next((a for a in linjer if a["prognose"] and a["kum_likviditet"] >= 0), None)
    top = max(linjer, key=lambda a: a["nav"])
    _fliser(s, [("Markedsværdi i dag", beloeb(r["total"]["markedsvaerdi_dkk"])),
                (f"Højeste NAV ({top['aar']})", beloeb(top["nav"])),
                (f"NAV ultimo {fem['aar']}", beloeb(fem["nav"])),
                ("Likviditet positiv fra", str(nul["aar"]) if nul else f"efter {p['slut_aar']}"),
                (f"TVPI {p['slut_aar']}", gange(_total_tvpi(p)))])
    soejler = []
    for f, res in p["fonde"].items():
        aar = {a["aar"]: a for a in res["linjer"]}
        soejler.append((f, [_mio(aar.get(a["aar"], {}).get("nav", 0)) for a in linjer],
                        farver[f], True))
    lin = [("Akkumuleret likviditet, " + (p["scenarie_navn"] or "excel").lower(),
            [_mio(a["kum_likviditet"]) for a in linjer], SORT, False)]
    for noegle, total in (p.get("scenarier") or {}).items():
        if noegle == p["scenarie"]:
            continue
        kum, aar = 0.0, {}
        for a in total:
            kum += a["netto"]
            aar[a["aar"]] = kum
        lin.append((f"Akkumuleret likviditet, {_scenarienavn(p, noegle).lower()}",
                    [_mio(aar.get(a["aar"])) for a in linjer],
                    SCENARIEFARVER.get(noegle, ROED), True))
    y = KURVE_Y + 0.05
    _tekst(s, X0, y, X1 - X0, 0.22, "NAV ved årets udgang pr. fond og akkumuleret likviditet",
           11, fed=True)
    _kombi(s, X0, y + 0.24, X1 - X0, fod.y() - 0.08 - y - 0.24, kat, soejler, lin)
    fod.tegn(s)
    return s


def prognose_pr_fond(prs, r, p):
    """Prognosen pr. fond: resttilsagn, kald og udlodninger de næste tre år og TVPI/IRR ved
    prognosens udgang."""
    aar0 = r["dato"].year
    s = _slide(prs, r, "Prognose pr. fond", "beløb i mio. DKK")
    fod = Fodnoter()
    rest_m = fod.maerke(f"Kun resten af {aar0}.")
    slut_m = fod.maerke(f"Ved prognosens udgang ({p['slut_aar']}), i DKK, inkl. NAV på det "
                        "tidspunkt.")
    fod.generel(_motor_note(p))
    aarene = [aar0, aar0 + 1, aar0 + 2]
    hoved = (["Fond", "Resttilsagn"] + [f"Kald {a}" + (rest_m if a == aar0 else "") for a in aarene]
             + [f"Udlodning {a}" + (rest_m if a == aar0 else "") for a in aarene]
             + ["TVPI" + slut_m, "IRR" + slut_m])
    raekker = [hoved]
    sum_k, sum_u = [0.0] * 3, [0.0] * 3
    for f in r["fonde"]:
        res = p["fonde"][f["fond"]]
        k = {a["aar"]: a for a in kommende(res["linjer"], aar0, 3)}
        kald = [k.get(a, {}).get("kald", 0.0) for a in aarene]
        udl = [k.get(a, {}).get("udlodning", 0.0) for a in aarene]
        sum_k = [x + y for x, y in zip(sum_k, kald)]
        sum_u = [x + y for x, y in zip(sum_u, udl)]
        raekker.append([f["fond"], beloeb(f["resttilsagn_dkk"])] + [beloeb(x) for x in kald]
                       + [beloeb(x) for x in udl] + [gange(res["tvpi"]), pct(res["irr"])])
    raekker.append(["I alt", beloeb(r["total"]["resttilsagn_dkk"])]
                   + [beloeb(x) for x in sum_k] + [beloeb(x) for x in sum_u]
                   + [gange(_total_tvpi(p)), pct(p["total_irr"])])
    _tabel(s, X0, Y_TOP, X1 - X0, raekker, bredder=[2.0, 1.0] + [0.85] * 6 + [0.75, 0.75],
           just=[V] + [H] * 9, raekke_h=0.32, pt=9, hoved=True, total=True, zebra=True)
    # TVPI pr. år pr. fond under tabellen
    y = Y_TOP + 0.32 * len(raekker) + 0.25
    hoejde = fod.y() - 0.08 - y - 0.24
    if hoejde > 1.2:
        _tekst(s, X0, y, X1 - X0, 0.22, "TVPI ved årets udgang pr. fond (DKK)", 11, fed=True)
        farver = _farver(r)
        linjer = [a for a in p["total"] if a["aar"] >= aar0 - 1]
        kat = [_aar_label(a, r) for a in linjer]
        serier = []
        for f, res in p["fonde"].items():
            aar = {a["aar"]: a for a in res["linjer"]}
            serier.append((f, [round(aar[a["aar"]]["tvpi"], 2)
                               if a["aar"] in aar and aar[a["aar"]]["tvpi"] else None
                               for a in linjer], farver[f], False))
        _linjediagram(s, X0, y + 0.24, X1 - X0, hoejde, kat, serier, '0.0"x"')
    fod.tegn(s)
    return s


def forudsaetninger(prs, r, p, cfg):
    """Bilag: forudsætningerne pr. fond og scenarierne."""
    s = _slide(prs, r, "Bilag: Forudsætninger", "satser pr. år")
    fod = Fodnoter("Kilde: config/forudsaetninger.yaml (P&P's antagelser).")
    afv_tekst = "Overstyret for denne investor."
    hoved = ["Fond", "Profil", "Vækst", "Løbetid", "Kaldsrater pr. leveår", "Kald til år",
             "Bow", "Løbende udlodning"]
    raekker = [hoved]
    for f in r["fonde"]:
        fs = p["forudsaetninger"][f["fond"]]
        ta, afv = fs["ta"], fs["afvigelser"]
        m = lambda *k, afv=afv: (fod.maerke(afv_tekst)
                                 if any(x in afv or f"ta.{x}" in afv for x in k) else "")
        raekker.append([f["fond"], fs["profil"] + m("profil"), pct(fs["vaekst"], 0) + m("vaekst"),
                        f"{fs['loebetid_aar']} år" + m("loebetid_aar"),
                        " / ".join(pct(x, 0) for x in ta["kaldsrater"]) + m("kaldsrater"),
                        str(ta.get("kald_til_aar") or "-") + m("kald_til_aar"),
                        style._dk(ta["bow"], 1) + m("bow"), pct(ta["udbytte"], 0) + m("udbytte")])
    _tekst(s, X0, Y_TOP, X1 - X0, 0.22, "Takahashi-Alexander (standard)", 10.5, fed=True,
           farve=SAGE)
    _tabel(s, X0, Y_TOP + 0.3, X1 - X0, raekker, bredder=[1.8, 1.3, 0.7, 0.7, 2.4, 0.8, 0.6, 1.1],
           just=[V, V, H, H, V, H, H, H], raekke_h=0.25, pt=8.5, hoved=True, zebra=True)
    y = Y_TOP + 0.3 + 0.25 * len(raekker) + 0.2
    aarene = list(range(r["dato"].year, p["slut_aar"] + 1))
    rcrd = [["Fond", "Sats"] + [str(a) for a in aarene]]
    for f in r["fonde"]:
        fs = p["forudsaetninger"][f["fond"]]
        rcrd.append([f["fond"], "RC"] + [pct(fs["rc"].get(a), 0) if fs["rc"].get(a) else "-"
                                         for a in aarene])
        rcrd.append(["", "RD"] + [pct(fs["rd"].get(a), 0) if fs["rd"].get(a) else "-"
                                  for a in aarene])
    _tekst(s, X0, y, X1 - X0, 0.22, "Excel-metoden: RC (andel af tilsagn) og RD (andel af NAV "
           "året før; 100 % = exit)", 10.5, fed=True, farve=SAGE)
    rh = min(0.2, (fod.y() - y - 0.4) / len(rcrd))
    _tabel(s, X0, y + 0.3, X1 - X0, rcrd, bredder=[1.8, 0.5] + [0.65] * len(aarene),
           just=[V, C] + [H] * len(aarene), raekke_h=rh, pt=7.5 if rh < 0.2 else 8, hoved=True)
    scen = cfg.get("scenarier") or {}
    fod.generel("Scenarier: " + "; ".join(
        f"{v.get('navn', k)}: vækst {'+' if v.get('vaekst', 0) >= 0 else ''}"
        f"{pct(v.get('vaekst', 0), 0)}, bow x {style._dk(v.get('bow', 1), 1)}, "
        f"løbende udlodning x {style._dk(v.get('udbytte', 1), 2)}"
        for k, v in scen.items() if k != "basis") + ".")
    fod.tegn(s)
    return s


def metode(prs, r, p):
    """Bilag: definitioner og metode i tekst."""
    s = _slide(prs, r, "Bilag: Metode og definitioner", "")
    punkter = [
        ("Data.", "Investorens transaktioner (tilsagn, kapitalkald, udlodninger, køb og salg af "
         "andele) og fondenes kvartalsvise NAV fra P&P's database. Valutakurser fra "
         "Danmarks Nationalbank."),
        ("Investorens NAV.", "Investorens ejerandel (antal aktier i forhold til fondens samlede "
         "antal på NAV-datoen) gange fondens egenkapital fra fondsregnskabet."),
        ("Markedsværdi.", "Seneste NAV plus kapitalkald og minus udlodninger efter NAV-datoen, "
         "omregnet til dagskurs."),
        ("Indbetalt og resttilsagn.", "Indbetalt er den del af tilsagnet, der er kaldt. "
         "Resttilsagn = tilsagn - indbetalt. Kontante betalinger kan afvige pga. rabat og "
         "true-up-rente ved closing."),
        ("Afkast.", "IRR er den årlige rente, der gør nutidsværdien af alle betalinger og "
         "markedsværdien lig nul. TVPI = (udlodninger + markedsværdi) / indbetalt. "
         "DPI = udlodninger / indbetalt."),
        ("Prognose (Takahashi-Alexander).", "Kapitalkald som en årlig andel af resttilsagnet "
         "efter fondens alder; udlodninger som en andel af NAV, der stiger mod løbetidens "
         "udgang; NAV vokser med P&P's forventede afkast. Tre scenarier varierer afkast og "
         "udlodningstempo."),
        ("Prognose (Excel-metoden).", "Den tidligere model: årlige satser for kald (RC, andel af "
         "tilsagnet) og udlodning (RD, andel af NAV året før) fastsat pr. fond og år."),
        ("Forbehold.", "Prognosen er et skøn. Faktiske kald, udlodninger og afkast afhænger af "
         "forvalternes beslutninger og markedsudviklingen og kan afvige væsentligt."),
    ]
    _punkter(s, X0, Y_TOP, X1 - X0, Y_NOTER - Y_TOP, punkter, pt=10)
    return s


def sammenligning(prs, r, p):
    """Bilag: TA-prognosen mod Excel-metoden (netto pr. år og TVPI/IRR pr. fond)."""
    if p["motor"] != "ta" or not p.get("excel"):
        return None
    s = _slide(prs, r, "Bilag: To prognosemetoder", "beløb i mio. DKK")
    fod = Fodnoter()
    fod.generel(_aar_note(r), "Excel-metoden med satserne på forrige side; Takahashi-Alexander i "
                f"scenariet {p['scenarie_navn']}.")
    hoved = ["Fond", "TVPI, TA", "TVPI, Excel", "IRR, TA", "IRR, Excel"]
    raekker = [hoved]
    for f in r["fonde"]:
        ta, ex = p["fonde"][f["fond"]], p["excel"][f["fond"]]
        raekker.append([f["fond"], gange(ta["tvpi"]), gange(ex["tvpi"]), pct(ta["irr"]),
                        pct(ex["irr"])])
    w = 4.2
    _tabel(s, X0, Y_TOP, w, raekker, bredder=[1.8, 0.8, 0.8, 0.8, 0.8], just=[V, H, H, H, H],
           raekke_h=0.3, pt=8.5, hoved=True, zebra=True)
    aar0 = r["dato"].year
    ta = [a for a in p["total"] if a["aar"] >= aar0]
    ex = {a["aar"]: a for a in p["excel_total"]}
    kat = [_aar_label(a, r) for a in ta]
    x = X0 + w + 0.4
    _tekst(s, x, Y_TOP, X1 - x, 0.22, "Netto cash flow pr. år", 11, fed=True)
    _kombi(s, x, Y_TOP + 0.24, X1 - x, fod.y() - 0.08 - Y_TOP - 0.24, kat,
           [("Takahashi-Alexander", [_mio(a["netto"]) for a in ta], SAGE, True),
            ("Excel-metoden", [_mio(ex[a["aar"]]["netto"]) if a["aar"] in ex else None
                               for a in ta], TAUPE, True)], [], stablet=False)
    fod.tegn(s)
    return s


# ---------- sidefod ----------

def sidefod(prs, investor_navn):
    """"Investor | Side n" nederst til højre på hver indholdsslide (masterens slidenummerfelt)."""
    layout = prs.slide_layouts[L_TEKST]
    ph_layout = next(ph for ph in layout.placeholders
                     if ph.placeholder_format.type == PP_PLACEHOLDER.SLIDE_NUMBER)
    for nr, s in enumerate(prs.slides, start=1):
        if s.slide_layout != layout:
            continue
        s.shapes.clone_placeholder(ph_layout)
        ph = next(ph for ph in s.placeholders
                  if ph.placeholder_format.type == PP_PLACEHOLDER.SLIDE_NUMBER)
        para = ph.text_frame.paragraphs[0]
        navn = para.add_run()
        navn.text, navn.font.bold = investor_navn, True
        para.add_run().text = " | Side "
        felt = para._p.makeelement(qn("a:fld"), {"id": f"{{{uuid.uuid4()}}}".upper(),
                                                 "type": "slidenum"})
        felt.append(para._p.makeelement(qn("a:rPr"), {"lang": "da-DK"}))
        tekst = para._p.makeelement(qn("a:t"), {})
        tekst.text = str(nr)
        felt.append(tekst)
        para._p.append(felt)
