"""Evalscripty pro Sentinel Hub (běží na serveru Copernicus nad každým pixelem).

Stejné vzorce (chlorofyl, zákal, plovoucí sinice, skóre) jsou v kappka/analysis.py,
aby statistiky i barevná mapa znečištění dávaly shodné výsledky.
"""

# Společné funkce pro Sentinel-2 L2A.
#  - Maskování oblačnosti: SCL (Sen2Cor scene classification) + CLD (pravděpodobnost oblaku)
#    + test na opar (modré pásmo nad vodou bývá < 0.1).
#  - Chlorofyl-a z NDCI (Mishra & Mishra 2012): pásmo B05 (705 nm) reaguje na chlorofyl.
#  - Zákal (NTU) podle Dogliotti et al. 2015 (červené pásmo, pro silný zákal NIR).
#  - Plovoucí sinicové povlaky („vodní květ“): voda s NDVI > 0.2 (povlak odráží v NIR jako vegetace).
_S2_COMMON = """
var BAD_SCL = [0, 1, 3, 8, 9, 10, 11];  // no data, saturace, stín mraku, mraky (3 úrovně), sníh

function isClear(s) {
  if (s.dataMask === 0) return false;
  if (BAD_SCL.indexOf(s.SCL) !== -1) return false;
  if (s.CLD > 20) return false;
  if (s.B02 > 0.12) return false;   // opar / tenká oblačnost nad vodou
  return true;
}

function chlorophyll(s) {
  var ndci = (s.B05 - s.B04) / (s.B05 + s.B04 + 1e-6);
  var chl = 14.039 + 86.115 * ndci + 194.325 * ndci * ndci;
  return Math.max(0, Math.min(chl, 400));
}

function turbidity(s) {
  var red = s.B04, nir = s.B08;
  var tRed = 228.1 * red / Math.max(1e-3, 1 - red / 0.1641);
  var tNir = 3078.9 * nir / Math.max(1e-3, 1 - nir / 0.2112);
  var t;
  if (red < 0.05) t = tRed;
  else if (red > 0.07) t = tNir;
  else { var w = (red - 0.05) / 0.02; t = (1 - w) * tRed + w * tNir; }
  return Math.max(0, Math.min(t, 1000));
}

function scum(s) {
  var ndvi = (s.B08 - s.B04) / (s.B08 + s.B04 + 1e-6);
  return ndvi > 0.2 ? 1 : 0;
}

function interp(x, pts) {
  if (x <= pts[0][0]) return pts[0][1];
  for (var i = 1; i < pts.length; i++) {
    if (x <= pts[i][0]) {
      var a = pts[i - 1], b = pts[i];
      return a[1] + (b[1] - a[1]) * (x - a[0]) / (b[0] - a[0]);
    }
  }
  return pts[pts.length - 1][1];
}

var CHL_PTS = %(chl_pts)s;
var TURB_PTS = %(turb_pts)s;
var SCUM_PTS = %(scum_pts)s;

function score(chl, turb, scumFrac) {
  var c = interp(chl, CHL_PTS), t = interp(turb, TURB_PTS), k = interp(scumFrac, SCUM_PTS);
  var mx = Math.max(c, t, k);
  return 0.5 * mx + 0.5 * (%(w_chl)s * c + %(w_turb)s * t + %(w_scum)s * k);
}
"""


def _common() -> str:
    from . import analysis as a

    return _S2_COMMON % {
        "chl_pts": [list(p) for p in a.CHL_POINTS],
        "turb_pts": [list(p) for p in a.TURB_POINTS],
        "scum_pts": [list(p) for p in a.SCUM_POINTS],
        "w_chl": a.WEIGHTS[0],
        "w_turb": a.WEIGHTS[1],
        "w_scum": a.WEIGHTS[2],
    }


S2_BANDS = '["B02", "B03", "B04", "B05", "B08", "SCL", "CLD", "dataMask"]'


def s2_statistics() -> str:
    """Statistiky kvality vody – bezoblačné pixely uvnitř (zmenšeného) polygonu."""
    return (
        """//VERSION=3
function setup() {
  return {
    input: [{bands: %s}],
    output: [
      {id: "chl", bands: 1, sampleType: "FLOAT32"},
      {id: "turb", bands: 1, sampleType: "FLOAT32"},
      {id: "scum", bands: 1, sampleType: "FLOAT32"},
      {id: "dataMask", bands: 1}
    ]
  };
}
"""
        % S2_BANDS
        + _common()
        + """
function evaluatePixel(s) {
  var ok = isClear(s) ? 1 : 0;
  return {chl: [chlorophyll(s)], turb: [turbidity(s)], scum: [scum(s)], dataMask: [ok]};
}
"""
    )


def s2_true_color() -> str:
    """Přirozené barvy se zesílením a lehkou gama korekcí."""
    return """//VERSION=3
function setup() {
  return {input: ["B02", "B03", "B04", "dataMask"], output: {bands: 4}};
}
function f(v) { return Math.pow(Math.min(1, Math.max(0, v * 3.0)), 0.8); }
function evaluatePixel(s) {
  return [f(s.B04), f(s.B03), f(s.B02), s.dataMask];
}
"""


def s2_pollution_map() -> str:
    """Barevná mapa skóre znečištění (zelená = čisto, červená = znečištěno, šedá = oblak)."""
    return (
        """//VERSION=3
function setup() {
  return {input: [{bands: %s}], output: {bands: 4}};
}
"""
        % S2_BANDS
        + _common()
        + """
var RAMP = [
  [0, 0x1a9850], [20, 0x91cf60], [40, 0xfee08b], [60, 0xfc8d59], [80, 0xd73027], [100, 0x7f0000]
];
var viz = new ColorRampVisualizer(RAMP);

function evaluatePixel(s) {
  if (s.dataMask === 0) return [0, 0, 0, 0];
  if (!isClear(s)) return [0.75, 0.75, 0.75, 0.6];
  var v = score(chlorophyll(s), turbidity(s), scum(s));
  var c = viz.process(v);
  return [c[0], c[1], c[2], 0.9];
}
"""
    )


def landsat_temperature() -> str:
    """Teplota hladiny z Landsat 8/9 TIRS B10 (jasová teplota v K) s korekcí emisivity vody.

    Bez atmosférické korekce – výsledek je odhad, obvykle o 1–3 °C nižší než skutečnost.
    Mraky z QA pásma (BQA/QA_PIXEL): bit 0 fill, 1 dilated cloud, 2 cirrus, 3 cloud, 4 shadow.
    """
    return """//VERSION=3
function setup() {
  return {
    input: [{bands: ["B10", "BQA", "dataMask"]}],
    output: [{id: "temp", bands: 1, sampleType: "FLOAT32"}, {id: "dataMask", bands: 1}]
  };
}
function bit(v, n) { return Math.floor(v / Math.pow(2, n)) % 2; }
function evaluatePixel(s) {
  var q = s.BQA;
  var bad = s.dataMask === 0 || bit(q, 0) || bit(q, 1) || bit(q, 2) || bit(q, 3) || bit(q, 4) || s.B10 < 200;
  var bt = s.B10;
  var lst = bt / (1 + (10.895e-6 * bt / 1.4388e-2) * Math.log(0.991));
  return {temp: [lst - 273.15], dataMask: [bad ? 0 : 1]};
}
"""
