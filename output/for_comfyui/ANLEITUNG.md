# ComfyUI: Erste Runde — genau so vorgehen

Für jedes Bild in diesem Ordner: in ComfyUI als **img2img** laden
(Workflow siehe `docs/comfyui.md`), mit dem passenden Prompt unten
generieren, Ergebnis unter gleichem Namen nach `output/painted/`
hochladen (GitHub-Web: Add file → Upload files). Dann Claude Bescheid
sagen — Claude schaut die Ergebnisse an und sagt dir, welche Regler du
ändern sollst.

**Gemeinsame Einstellungen für Runde 1:**
Denoise **0.55** | Steps 30 | CFG 6.5 (SDXL) | Sampler dpmpp_2m / karras

**Negativ-Prompt (für alle gleich):**

    pixel art, cartoon, childish, blurry, text, watermark, grid lines,
    ugly, low quality, photo, 3d render look, plastic, clay

---

## zonen_weltkarte.png  (die Spielwelt: Zellen, Schluchten, Brücken)

    epic hand-painted fantasy MMORPG world map, top-down, lush green
    realms separated by deep dark chasms, wooden rope bridges, winding
    sandy paths, small settlements, dramatic soft lighting, rich muted
    colors, painterly concept art, intricate detail, masterpiece

## insel_weltkarte.png  (Kontinent-Übersicht)

    hand-painted fantasy world map, top-down, emerald islands in a deep
    blue ocean, white mountain peaks, dense forests, golden beaches,
    painterly style like a AAA game loading screen map, soft shadows,
    rich color, high detail

## feuer_arena.png  (PvP-Arena)

    top-down view of an ancient gladiator arena surrounded by a moat of
    glowing molten lava, cracked obsidian rock, ember particles, torch
    light, dark fantasy MMORPG battle arena, hand-painted game art,
    dramatic lighting, high detail

## dorf_szene.png  (spielbare Dorfzone)

    hand-painted top-down fantasy village, cozy cottages with red roofs,
    dirt paths, stone plaza with well, lush forest surrounding a
    clearing, sparkling pond, warm afternoon light, painterly MMORPG
    game map, style of high-end 2d game art, rich detail

---

**Wichtig:** Nichts weiter verstellen in Runde 1 — erst Ergebnisse
hochladen, dann justieren wir gezielt (Denoise rauf = schöner/freier,
runter = näher am Layout; Prompt-Feinschliff macht Claude).
