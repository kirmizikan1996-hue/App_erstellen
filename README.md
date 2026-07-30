# MMORPG Map-Pipeline (2D Topdown)

Ein Setup, mit dem Claude professionelle, **spielbare** 2D-Topdown-Maps baut —
als Daten (Tiled-JSON), nicht als Pixelmalerei. Die Grafikqualität kommt aus
dem Tileset, die Map-Qualität aus Logik + visueller Iteration.

## Der Workflow (so arbeitest du mit Claude)

```
Du beschreibst die Map        ("Hafenstadt, Markt in der Mitte, Leuchtturm im Süden")
        │
Claude baut/ändert Map-Daten  (maps/*.json — Tiled-kompatibel, mit Autotiling)
        │
Renderer erzeugt PNG          (tools/render_tilemap.py)
        │
Claude BETRACHTET das PNG     (sieht Fehler selbst und korrigiert)
        │
   … iterieren bis es sitzt, dann Export in deine Engine
```

Der entscheidende Punkt: Claude kann gerenderte Bilder ansehen. Dadurch
entsteht ein Feedback-Loop wie bei einem Level-Designer, nur automatisiert.

## Quickstart

```bash
pip install pillow numpy

python3 tools/make_tileset.py        # Starter-Tileset generieren
python3 tools/build_demo_map.py      # Demo-Dorf bauen (Autotiling)
python3 tools/render_tilemap.py maps/demo_village.json   # Vorschau-PNG

python3 tools/worldgen.py --seed 42  # Bonus: prozedurale Weltkarte/Minimap
```

## Struktur

| Pfad | Zweck |
|---|---|
| `assets/tilesets/` | Tilesets (PNG + Metadaten). **Hier Profi-Assets ablegen!** |
| `maps/` | Map-Definitionen im Tiled-JSON-Format (spielbar: Ground/Deko/Kollision) |
| `tools/make_tileset.py` | Generiert das Starter-Tileset (56 Tiles, 32px, inkl. Wang-Übergänge) |
| `tools/build_demo_map.py` | Baut Maps aus High-Level-Beschreibung mit Autotiling |
| `tools/render_tilemap.py` | Rendert jede Tiled-JSON-Map als PNG (`--collision`, `--grid`, `--scale`) |
| `tools/worldgen.py` | Prozedurale Weltkarten (Biome, Relief, Flüsse, Städte) |
| `output/` | Gerenderte Vorschauen |

## Gemalter Look (kein Pixel-Art): KI-Bildgenerator anbinden

Für handgemalte MMORPG-Optik wird Claude mit einem Bildgenerator verbunden.
Claude liefert die **Struktur** (Layout, Biome, Kollision), die Bild-KI liefert
die **Malerei** (img2img über das Layout — Geometrie bleibt spielbar), Claude
**betrachtet und iteriert**. Das Skript dafür liegt bereit: `tools/stylize.py`.

**Einmalige Einrichtung (5 Minuten, auf claude.ai/code):**

1. Environment-Einstellungen dieses Projekts öffnen → **Netzwerkzugriff**:
   `api.replicate.com` freigeben (oder vollen Netzwerkzugriff aktivieren).
   Docs: https://code.claude.com/docs/en/claude-code-on-the-web
2. Auf replicate.com einen Account anlegen und API-Token holen
   (Pay-as-you-go, Flux-Bild ≈ 3 Cent).
3. Den Token als Umgebungsvariable/Secret `REPLICATE_API_TOKEN` im
   Environment hinterlegen.
4. Claude sagen: *„Male die Weltkarte im Stil von <Referenz>"* — fertig.
   Alternative: `OPENAI_API_KEY` + Freigabe von `api.openai.com` (gpt-image-1).

**Spielbare Maps im gemalten Stil** funktionieren nach dem Prinzip vieler
2D-MMOs: gemaltes Hintergrundbild + unsichtbare Kollisionsdaten. Claude
rendert das Layout zonenweise, lässt jede Zone übermalen und behält die
Kollisions-/Objektdaten aus `maps/*.json` — Spieler laufen auf der Malerei.

**Alternativen ohne API:**
- **ComfyUI/Stable Diffusion lokal** auf deinem PC (kostenlos, ControlNet
  hält sich exakt an Claudes Layout) — Claude schreibt dir die Workflows.
- **Gemalte (nicht-Pixel) Asset-Packs**: craftpix.net (auch gratis Sektion),
  itch.io Suchbegriff "hand-painted tileset", Unity Asset Store.
- **Artist beauftragen** fürs finale Tileset — Claude baut damit die Maps.

## Von "gut" zu "AAA": Profi-Tilesets einbinden

Das generierte Starter-Tileset ist bewusst austauschbar. Für echte
Profi-Optik lädst du ein fertiges Tileset herunter und legst es in
`assets/tilesets/<name>/` ab — Claude passt die Tile-IDs an und alle
Maps rendern sofort in der neuen Optik. Empfehlungen:

- **Kenney** (kenney.nl) — riesige CC0-Packs (RPG Base, Tiny Town, Roguelike), kostenlos, kommerziell nutzbar
- **LimeZu "Modern Interiors/Exteriors"** (itch.io) — sehr hochwertig, günstig
- **Szadi art. / Pixel-Boy** (itch.io) — RPG-Fantasy-Tilesets
- **OpenGameArt LPC-Serie** — kostenlos (Lizenz CC-BY-SA beachten)

Wichtig beim Ablegen: Tilegröße (16/32/48px) und Spaltenzahl in einer
`tileset_meta.json` daneben notieren (Format siehe `assets/tilesets/basic/`).

## In die Engine bringen (Spieler laufen drauf)

Die Maps sind **Tiled-kompatibles JSON** mit `collision`-Layer:

- **Godot**: Tiled-Importer-Plugin oder direkt TileMapLayer aus JSON befüllen
- **Phaser 3** (Web-MMORPG): `this.load.tilemapTiledJSON(...)` — funktioniert direkt
- **Unity**: SuperTiled2Unity
- **Eigener Client**: `layers[].data` ist ein flaches Array aus Tile-IDs (gid−1), `collision`-Layer ≠ 0 = blockiert
- Der `overlay`-Layer (Baumkronen) gehört ÜBER den Spieler-Sprite gerendert — so läuft die Figur hinter Bäumen entlang (Tiefenwirkung)

Außerdem lohnt sich der **Tiled-Editor** (mapeditor.org, kostenlos): Damit
kannst du jede von Claude gebaute Map von Hand nachpolieren — und Claude kann
deine Handarbeit wieder einlesen und weiterbauen. Alternative: **LDtk**.

## Was du Claude sagen kannst

- „Bau eine Wüstenstadt 60×60 mit Oase und Basar" → neues Map-JSON + Render
- „Der Wald oben rechts ist zu dicht, mach eine Lichtung mit Schrein" → Iteration
- „Generiere 5 Dungeon-Layouts, zeig sie mir nebeneinander" → Varianten-Vergleich
- „Exportiere die Map für Phaser/Godot" → Engine-Integration
- „Schreib einen Cave-Generator (BSP/Cellular Automata)" → neue Generatoren
