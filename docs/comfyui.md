# ComfyUI-Anbindung — Plan & Anleitung

Ziel: Claudes Layout-Karten (Struktur + Kollision) werden in ComfyUI
handgemalt-schön übermalt (img2img), die Karte bleibt spielbar.

## Zwei Betriebsarten

### A) Vollautomatisch (empfohlen): Claude Code lokal auf deinem Rechner

ComfyUI hat eine lokale API (`http://127.0.0.1:8188`). Läuft Claude Code
**auf demselben Rechner** (Desktop-App oder CLI, im Ordner dieses Repos),
kann Claude den kompletten Loop selbst fahren:
Layout rendern → an ComfyUI schicken → Ergebnis ansehen → Prompt/Denoise
nachstellen → wiederholen, bis es sitzt.

Vorbereitung deinerseits: ComfyUI starten, Claude Code installieren
(https://claude.com/claude-code), dieses Repo clonen, dann z.B. sagen:
„Verbinde dich mit meinem ComfyUI auf Port 8188 und male output/world_42.png".

### B) Manuell: Diese Cloud-Session + du als Brücke

1. Claude rendert hier Layouts und pusht sie nach `output/`
2. Du ziehst das PNG lokal in ComfyUI, generierst, und lädst das Ergebnis
   ins Repo hoch (GitHub-Web: "Add file" → `output/painted/`)
3. Claude schaut es an, sagt dir konkret, welche Regler du ändern sollst

## Der Basis-Workflow in ComfyUI (img2img)

Nodes: **Load Checkpoint** → **Load Image** (Claudes Layout) →
**VAE Encode** → **KSampler** → **VAE Decode** → **Save Image**,
plus zwei **CLIP Text Encode** (Positiv/Negativ) an den KSampler.

Empfohlene Einstellungen für den Start:
- Checkpoint: ein SDXL-Modell (z.B. Juggernaut XL) oder Flux
- **Denoise: 0.5–0.6** (der wichtigste Regler: niedrig = Layout bleibt,
  hoch = KI malt freier)
- Steps 30, CFG 6–7 (SDXL)

Positiv-Prompt (Startpunkt, passen wir an deinen Stil an):

    hand-painted fantasy MMORPG world map, top-down view, lush green
    meadows, dense forests, winding dirt paths, cozy village with red
    roofs, sparkling lake, soft warm sunlight, rich saturated colors,
    painterly game art, high detail, style of professional game

Negativ-Prompt:

    pixel art, blurry, text, watermark, grid, ugly, low quality, photo,
    3d render, isometric

## Ausbaustufe: ControlNet (Geometrie exakt einhalten)

Mit ControlNet (z.B. `controlnet-union-sdxl`, Typ "segmentation" oder
"canny") hält sich die KI präzise an Claudes Layout — wichtig, damit
Kollisionsdaten und Malerei deckungsgleich bleiben. Claude kann die
Layouts dafür als Farbflächen-Segmentierungskarte exportieren
(ein kleines Skript, das wir bei Bedarf ergänzen).

## Für große, spielbare Zonen

Große Maps werden in Kacheln (z.B. 1024x1024 mit Überlappung) gemalt und
zusammengesetzt; die Kollisions-/Objektdaten kommen weiter aus
`maps/*.json`. Den Kachel-Zerleger und -Zusammensetzer schreibt Claude,
sobald der Stil steht.
