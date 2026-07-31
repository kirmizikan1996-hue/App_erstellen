# Karten-Learnings — was wir für zukünftige Karten wissen müssen

Lebendes Dokument. Hier landet alles, was wir beim Bauen und Malen der
Zonen-Karten gelernt haben, damit wir es nicht zweimal herausfinden müssen.

---

## 0. Die wichtigste Regel

**img2img kann nur übermalen, was schon da ist.**

ComfyUI erfindet keine Spielmechanik. Wenn es auf der Layout-Karte keine
breiten Wege, keine Arenen und keine Pflasterplätze gibt, dann zaubert auch
der beste Prompt bei keinem Denoise-Wert welche hin — es entstehen höchstens
zufällige Flecken an zufälligen Stellen, die nicht zu `collision.png` passen.

→ Erst das **Layout** richtig bauen (`mapgen/`), dann malen lassen.
→ Alles, was der Spieler *benutzt* (Wege, Plätze, Arenen, Brücken), muss im
   Layout breit und deutlich genug sein, um einen Denoise-Durchgang zu überleben.

---

## 1. ComfyUI-Setup (lokaler Rechner, RTX 4090)

| Punkt | Wert |
|---|---|
| API | `http://127.0.0.1:8188` |
| Tool | `tools/comfy_paint.py` |
| Checkpoint | `sd_xl_base_1.0.safetensors` (aktuell der **einzige**) |
| Modelle prüfen | `python tools/comfy_paint.py --list-checkpoints` |

ComfyUI Desktop liegt unter `%LOCALAPPDATA%\Programs\Comfy Desktop`.
Muss **laufen**, sonst bricht das Tool mit „nicht erreichbar" ab.

**Wunsch für später:** ein painterly-Checkpoint (Juggernaut XL, DreamShaper XL)
statt SDXL base — base ist für handgemalte Fantasy-Optik nur Mittelmaß.
Und **ControlNet** (canny/segmentation), siehe Abschnitt 5.

---

## 2. Denoise — der wichtigste Regler

Getestet auf `mapgen/zone_neu/render_final.png` (2048×2048), Seed fix,
damit nur Denoise variiert:

| Denoise | Ergebnis |
|---|---|
| **0.55** | **Sweet Spot.** Wege klar, Brücken da, Dörfer lesbar, trotzdem malerisch. |
| 0.58 | Wege werden schon blasser, kein Gewinn beim Wasser. |
| 0.60 | Wege dünn und unterbrochen, Brücken matschig. |
| 0.65 | Schönste Malerei (Wassertiefe, Details) — **aber Wege und ALLE Brücken weg.** |

**Merksatz:** Struktur überlebt unten, Schönheit entsteht oben.
Für eine *spielbare* Karte gewinnt immer die Struktur → **0.55**.

Weitere Parameter: Steps 40 und CFG 7 sind ein guter Standard.
CFG 9 zieht die Wege minimal kräftiger nach, ohne Struktur zu kosten.

---

## 3. Prompt-Handwerk

**Was funktioniert:**
- Genau das beschreiben, was auf dem Layout schon liegt — dann *verstärkt*
  das Modell die Strukturen, statt sie zu ersetzen.
- Gameplay-Elemente explizit benennen: „clearly visible winding dirt roads
  connecting the villages", „wooden rope bridges spanning the channels".
  Ohne diese Wörter frisst der Sampler sie zuerst weg.

**Was schiefgeht:**
- **Starke Gewichtung `(...:1.5)` blutet aus.** „white foam surf" mit 1.5
  hat die *sandigen Dorfplätze* in weiße Schaumflecken verwandelt und alle
  drei Dörfer zerstört. Gewichte ≤ 1.3 halten, oder ganz weglassen.
- Begriffe, die auf mehrere Flächen passen (Schaum ↔ heller Sand), meiden.

**Negativ-Prompt — Pflicht:**
SDXL malt bei Karten ungefragt einen **Bilderrahmen** aus Holzplanken an die
Ränder. Dagegen hilft:

    picture frame, border, wooden planks at edge, paper edge, vignette

Dazu der Standard: `pixel art, cartoon, childish, blurry, text, watermark,
grid lines, ugly, low quality, photo, plastic, clay, flat color, empty`

---

## 4. Seed ist kein Detail

Gleiche Settings, nur anderer Seed → deutlich andere Qualität.
Seed **777** lieferte ein sauberes Städtchen und **alle drei Brücken**
klar erkennbar; Seed 1234 bei identischen Settings deutlich schwächer.

→ Bei einem guten Setting **mehrere Seeds durchprobieren** und den besten
   nehmen. Das ist billiger als am Prompt zu feilen.

---

## 5. Flaches Wasser — GELÖST

Ausgangsproblem: Große, einfarbige Flächen bekommen bei Denoise 0.55 zu
wenig Rauschen, um Struktur zu entwickeln. Denoise hoch → Wege kaputt,
Prompt-Gewichtung hoch → Ausbluten, CFG hoch → kein Effekt.

**Die Lösung war das Layout, nicht der Sampler.** Seit `zone_arena.py` das
Wasser selbst mit Tiefenverlauf, Wellenbändern, Glitzern und Schaumsaum
malt, macht ComfyUI daraus auf Anhieb echtes Meer mit Wellen, Untiefen und
sogar kleinen Booten. Genau Regel 0: **der Sampler verstärkt, was da ist.**

→ Gilt für alles: was schön werden soll, muss im Layout schon angelegt sein.

**ControlNet** (canny/segmentation) bleibt trotzdem der nächste sinnvolle
Ausbauschritt — damit könnte man Denoise gefahrlos auf 0.7+ ziehen und
Geometrie trotzdem exakt halten.

**2048×2048 mit SDXL:** SDXL ist auf 1024 trainiert. Bei 2048 im img2img geht
es dank niedrigem Denoise gut, aber bei hohem Denoise verdoppelt es Details.
Für größere Karten: Kacheln mit Überlappung.

---

## 5b. Fehldeutungen — was der Sampler falsch versteht

Das ist die wichtigste Erfahrung aus der zweiten Runde. SDXL liest Formen
und Farben *semantisch*. Vier Fallen, alle selbst erlebt:

| Im Layout | Wird gemalt als | Fix |
|---|---|---|
| Kaltgraues Pflaster | **Fluss mit Wasserfällen** | Warmer Sandstein statt kaltem Grau |
| Heller Kreis mit dunklem Ring | **Teich / Oase** | Fleckiger Boden, kein glatter heller Kern, keine klare Ringkante |
| Dreieckige Zeltdächer | **Häuser mit rotem Dach** → Arena wird Dorf | Zelte weglassen, stattdessen Knochenfeld |
| Große einfarbige Fläche | bleibt einfarbig | Struktur selbst reinmalen (s. o.) |

**Merksatz:** Jede Form, die zufällig wie etwas anderes aussieht, *wird* zu
etwas anderem. Farbe und Silhouette sind die Sprache, in der man mit dem
Sampler redet.

---

## 5c. Negativ-Prompt: nicht mit Kanonen auf Spatzen

Um Häuser in den Arenen zu verhindern, stand `buildings in the clearing,
houses on bare dirt` im Negativ-Prompt. Ergebnis: **alle Dörfer der ganzen
Karte waren weg.** Der Negativ-Prompt wirkt global, nicht lokal.

→ Nie etwas negativ prompten, das man woanders auf der Karte *haben* will.
   Lokale Probleme im Layout lösen, nicht im Prompt.

**2048×2048 mit SDXL:** SDXL ist auf 1024 trainiert. Bei 2048 im img2img geht
es dank niedrigem Denoise gut, aber bei hohem Denoise fängt es an, Details zu
verdoppeln. Für noch größere Karten: Kacheln mit Überlappung.

---

## 5d. Aktueller Stand der Pipeline

`mapgen/zone_arena.py` ist der Generator, der die Gameplay-Anforderungen
umsetzt (reine Python/PIL-Pipeline, **kein Blender nötig**):

    python3 mapgen/zone_arena.py --seed 7 --islands 14 --out mapgen/zone_arena

Erzeugt `render_base.png` (geht so in ComfyUI), `collision.png` und
`layout.json` (Arenen inkl. **Winkel der vier Schneisen**, Dörfer, Brücken,
Baumpositionen für Unity).

Bewährte Mal-Einstellung für dieses Layout:
**Denoise 0.58 | Steps 40 | CFG 7 | Seed 777**

Hinweis zu Blender: `blender_terrain.py` läuft nur *innerhalb* von Blender
(`bpy`). Blender ist hier nur über Steam installiert und lief nicht — für den
schnellen Iterationsloop ist die PIL-Pipeline ohnehin praktischer.

**Offener Punkt:** Die Arenen werden noch oft als kleine Siedlung gemalt
statt als Monsterlager. Die Geometrie stimmt (Position + 4 Schneisen stehen
exakt in `layout.json`, Unity kann die Monstergruppen also korrekt setzen) —
nur die *Optik* ist noch nicht eindeutig „wildes Revier". Nächster Versuch:
Arena weiter vergrößern, Umgebung dunkler/toter, mehr Kadaver-Silhouetten.

---

## 5e. Der Maßstabsfehler — zwei Artefakte statt einem

**Ein einzelnes PNG kann nicht gleichzeitig Übersichtskarte und begehbarer
Boden sein.** Das war der Denkfehler in der ersten Runde.

Die Zahlen, die es entschieden haben:

| | |
|---|---|
| `maps/demo_village.json` | 48 × 36 Tiles = 1536 × 1152 px — für *ein* Dorf |
| Gemalte Zonenkarte | 2048 × 2048 px — für 14 Inseln, 3 Städte, 4 Arenen |
| Ein Haus im Tileset | 5 × 4 Tiles = **160 px** breit |
| Eine ganze Stadt auf der gemalten Karte | **~200 px** breit |

Ein einzelnes Haus ist also fast so groß wie dort eine komplette Stadt —
Faktor ~10. Dazu kommt die Texeldichte: auf Spielergröße gezoomt ist im
gemalten PNG schlicht keine Information mehr da, es wird Matsch.

**Aufteilung, die funktioniert:**

* **Übersichtskarte** — `zone_arena.py` + ComfyUI → gemaltes PNG.
  Für Weltkarte, Minimap, Ladebildschirm.
* **Begehbare Zone** — `zone_tiles.py` → Tiled-Map im 32-px-Raster mit
  `ground`/`decoration`/`overlay`/`collision`. Darauf läuft der Spieler.

Beide kommen aus **demselben** `layout.json` (Wege, Arenen, Dörfer, Bäume),
darum zeigen sie dieselbe Welt.

    python3 tools/make_tileset_painted.py                 # Tileset bauen
    python3 mapgen/zone_arena.py --seed 7                 # Welt + Übersicht
    python3 mapgen/zone_tiles.py --center capital --out maps/zone_hauptstadt.json
    python3 mapgen/zone_tiles.py --center arena0 --out maps/zone_arena0.json
    python3 tools/render_tilemap.py maps/zone_arena0.json --collision

Eine Zone ist 128 × 128 Tiles = 4096 × 4096 px und deckt ~620 Welt-Pixel ab
(≈4,8 Welt-px pro Tile). Ursprung und Maßstab stehen als `world_origin_x/y`
und `world_px_per_tile` in den Map-Properties — damit lässt sich jede
Zonenposition zurück auf die Weltkarte rechnen.

---

## 5f. Fallen beim Tile-Bau (alle selbst reingelaufen)

* **Tile-Index 0 ist ein echtes Tile.** In Tiled bedeutet `0` „leer", die
  Tileset-IDs fangen aber bei 0 an. `grass_1` hatte ID 0 → jedes vierte
  Grasfeld wurde zum schwarzen Loch. Ground-Layer immer `id + 1` schreiben,
  ohne `if`.
* **Reihenfolge der Platzierung entscheidet.** Erst Wald, dann Häuser → es
  passt kein Haus mehr an den Platzrand (18 Häuser wurden zu 1). Bebauung
  zuerst, Deko danach.
* **Abstand aus der Sprite-Größe rechnen.** Ein 5×4-Haus mit `pad=1` braucht
  eine 7×6 freie Fläche; „knapp neben den Platz" reicht nicht, der halbe
  Fußabdruck liegt sonst im Pflaster.
* **Wang-Index 15 = komplett innen.** Nimmt man dafür weiter das
  Übergangstile, besteht jede große Fläche aus *einem* wiederholten Tile und
  sieht wie Tapete aus. Für 15 die Vollton-Varianten ziehen.
* **Schneisen nicht als anderes Material durch die Arena ziehen** — sie
  zerschneiden die Fläche in Fetzen. Gleiches Material, nur nach außen.
* **Arenen brauchen eine Wand.** Ein Erdfleck im offenen Gras liest sich
  nicht als Arena. Erst der Waldgürtel mit Lücken an den vier Schneisen
  macht daraus eine Kampffläche, die man aus genau vier Richtungen betritt.
* **Weltradius ≠ Zonenradius.** Die Arena 1:1 aus der Weltkarte übernommen
  wären >40 Tiles — ein Drittel der Zone. Auf `tiles * 0.105` gedeckelt.

---

## 6. Layout-Regeln fürs Gameplay

Der Spieler **läuft** auf dieser Karte — das Layout muss das hergeben:

- **Wege breit genug.** 13 px auf 2048 (≈0,6 %) ist zu dünn; sie überleben
  den Malprozess kaum und sehen nicht nach begehbarer Straße aus.
  → Hauptstraßen deutlich breiter, mit Pflaster und sichtbarem Rand.
- **Wegehierarchie:** breite Pflaster-Hauptstraße zwischen den Orten,
  schmalere Erdpfade als Abzweige. Das gibt der Karte Lesbarkeit.
- **Monster-Arenen:** offene Kampfflächen mit **vier Zugängen** (N/O/S/W),
  damit man Gruppen aus mehreren Richtungen ziehen und kiten kann.
  Rundum Platz lassen — keine Bäume/Felsen direkt an der Kampffläche.
- **Bäume kommen nicht ins Bild**, sondern als Positionen in JSON — in Unity
  werden sie als Assets mit Collider gesetzt. (So macht es `channel_map.py`.)
- `collision.png` und die gemalte Karte müssen **deckungsgleich** bleiben.
  Deshalb Denoise niedrig halten und nach jedem Malen gegenprüfen.

---

## 7. Arbeitsweise, die sich bewährt hat

1. `--list-checkpoints` — erst prüfen, was überhaupt da ist.
2. Layout bauen/ändern, Basis-PNG rendern.
3. Mit **festem Seed** eine Denoise-Reihe fahren (nur *eine* Variable ändern).
4. Jedes Ergebnis **wirklich ansehen**, nicht nur „fertig" melden.
5. Sitzt das Setting → mehrere Seeds, besten auswählen.
6. Gute Ergebnisse nach `output/painted/`, Zwischenschritte gehören da nicht hin.

**Nicht vergessen:** Ein kaputtes PNG (0 Byte / nur Nullen) sieht im
Dateibrowser normal aus. Ergebnisse immer öffnen, bevor man sie commitet —
`output/painted/v1_d055.png` war genau so eine Leiche.
