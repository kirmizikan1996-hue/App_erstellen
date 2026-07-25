# Map-Generator für das 2D-MMORPG

Erzeugt große Weltkarten im handgemalten Stil.

## Nutzung

```
pip install numpy pillow
python3 generate_map.py --size 4096 --seed 42 --out output
```

## Ausgabe

| Datei | Zweck |
|---|---|
| `map.png` | Sichtbare Boden-Ebene (in Unity als Sprite/Textur importieren) |
| `biomes.png` | Farbcodierte Biom-Daten (Wasser/Strand/Wiese/Wald/Gebirge) für Gameplay und Asset-Platzierung |
| `collision.png` | Weiß = blockiert (Wasser, Hochgebirge), Schwarz = begehbar |
| `map_meta.json` | Seed und Schwellwerte der Generierung |

## Unity-Import

1. `map.png` ins Projekt ziehen, Texture Type: *Sprite (2D and UI)*, Max Size erhöhen (z. B. 4096/8192).
2. Als Hintergrund-Sprite in die Szene legen (Sorting Layer „Ground“).
3. Häuser, Brücken usw. als eigene Sprites auf höheren Sorting Layers platzieren.
4. `collision.png` kann per Skript in Collider oder ein Begehbarkeits-Grid übersetzt werden.
