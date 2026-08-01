# Zone nach Unity bringen

Schritt für Schritt vom generierten Ordner ins laufende Projekt.

---

## 0. Was du brauchst

Nach einem Lauf von

```bash
python3 mapgen/zone_compose.py --tiles 256 --out maps/zone_furt.json
```

liegen vier Dinge bereit:

| Datei | wofür |
|---|---|
| `maps/zone_furt.json` | die Tiled-Map (Ebenen ground/decoration/overlay/collision) |
| `maps/zone_furt_collision.png` | Kollisionsmaske, **weiß = blockiert** |
| `maps/zone_furt_meta.json` | Lager, Arena, Stadt, Furten — für Spawns |
| `assets/tilesets/painted/tileset.png` | das Tileset |

---

## 1. Dateien ins Projekt kopieren

**Die Ordnerstruktur muss erhalten bleiben**, weil die Map das Tileset über
einen relativen Pfad referenziert (`../assets/tilesets/painted/tileset.png`):

```
Assets/
  Zones/
    maps/zone_furt.json
    maps/zone_furt_collision.png
    maps/zone_furt_meta.json
    assets/tilesets/painted/tileset.png
```

Liegt das Tileset woanders, findet der Importer es nicht und die Map bleibt leer.

---

## 2. SuperTiled2Unity installieren

Window → Package Manager → **+** → *Add package from git URL*:

```
https://github.com/Seanba/SuperTiled2Unity.git?path=/SuperTiled2Unity/Assets/SuperTiled2Unity
```

Danach importiert Unity `.json`-Tiled-Maps automatisch. Ein Klick auf die
Map im Projektfenster zeigt den Import-Inspector; von dort ins Scene-Fenster
ziehen.

---

## 3. Tileset-Import einstellen (der häufigste Fehler)

Das `tileset.png` anklicken und im Inspector setzen:

| Einstellung | Wert | warum |
|---|---|---|
| Texture Type | Sprite (2D and UI) | |
| **Filter Mode** | **Point (no filter)** | sonst wird Pixel-Art matschig |
| **Compression** | **None** | sonst Farbartefakte an Tile-Kanten |
| **Pixels Per Unit** | **32** | dann ist **1 Tile = 1 Unity-Unit** |
| Wrap Mode | Clamp | |
| Max Size | 2048 oder größer | Sheet nicht herunterskalieren lassen |

In den SuperTiled2Unity-Einstellungen zusätzlich **„Pixels Per Unit" auf 32**
setzen — sonst passen Map und Kollision nicht zusammen.

**Zu Nähten zwischen Tiles:** Wenn beim Bewegen dünne Linien aufblitzen, in
den SuperTiled2Unity-Projekteinstellungen *Edges Are Extruded* aktivieren und
die Kamera auf ganze Pixel einrasten lassen (Pixel Perfect Camera).

---

## 4. Ebenen richtig sortieren

Der `overlay`-Layer (Häuser, Zelte, Totems) gehört **über** den Spieler,
`ground` und `decoration` darunter. Sonst läuft die Figur vor den Dächern.

| Layer | Sorting Order |
|---|---|
| ground | 0 |
| decoration | 10 |
| Spieler | 20 |
| overlay | 30 |

Die `collision`-Ebene auf unsichtbar lassen — sie ist nur Datenträger.

---

## 5. Kollision aufbauen

`unity/ZoneImport.cs` nach `Assets/Scripts/` kopieren.

1. Bei `zone_furt_collision.png` im Inspector **Read/Write Enabled** anhaken
   und ebenfalls **Filter Mode: Point**, **Compression: None** setzen.
2. Leeres GameObject anlegen → **Tilemap**-Komponente + **TilemapCollider2D**
   + **Rigidbody2D (Body Type: Static)** + **CompositeCollider2D**.
   Am TilemapCollider2D **Used By Composite** anhaken — das fasst tausende
   Einzelkacheln zu wenigen Polygonen zusammen, sonst wird die Physik langsam.
3. `ZoneCollisionBuilder` auf dasselbe Objekt legen, Maske, Tilemap und ein
   beliebiges Tile zuweisen.
4. Im Kontextmenü der Komponente **„Kollision aufbauen"** ausführen.

Die Kollisions-Tilemap darf denselben Renderer wie die anderen haben — setz
die Farbe auf transparent oder deaktiviere den TilemapRenderer.

---

## 6. Monster spawnen

`ZoneSpawner` auf ein leeres GameObject legen und `zone_furt_meta.json` als
TextAsset zuweisen. Dann pro Revierart ein Prefab eintragen:

| type | Bedeutung |
|---|---|
| `banditen` | Zeltlager mit Feuerstellen |
| `untote` | Knochenfeld mit Totem |
| `bestien` | Baumstämme und Felsen |
| `spinnen` | Nest im hohen Gras |
| `ruine` | Felsen und Schädel |

Jedes Lager trägt `tier`: **`kern`** liegt in einem der drei Jagdreviere und
bekommt mehr Monster, **`rand`** ist eine ruhigere Zone. Die Anzahl je Stufe
stellst du pro Prefab ein (`countKern` / `countRand`).

Bei ausgewähltem Objekt zeichnet das Skript alle Lagerradien als Gizmos —
so siehst du die Farmspots direkt in der Szene, bevor du Prefabs hast.

---

## 7. Koordinaten

Tiled zählt **y nach unten**, Unity **nach oben**. Alle Werte in
`*_meta.json` sind Tile-Koordinaten mit Ursprung oben links. Umrechnung
(steckt in `ZoneCoords`):

```csharp
world = new Vector3(x + 0.5f, -(y + 0.5f), 0f);   // bei PPU = 32
```

Bei **Pixels Per Unit = 32** entspricht 1 Tile genau 1 Unity-Unit — damit
sind alle Radien aus der Metadatei direkt als Weltmaß verwendbar.

---

## 8. Alternative ohne SuperTiled2Unity

Wenn du den Importer nicht willst: das gerenderte PNG
(`tools/render_tilemap.py`) als einzelnes Sprite verwenden und nur Kollision
und Spawns aus den Beigaben ziehen. Schneller eingerichtet, aber:

* 8192 × 8192 als eine Textur ist speicherhungrig (Unity-Limit beachten,
  ggf. in Kacheln schneiden)
* keine Tile-Wiederverwendung, Änderungen erfordern neues Rendern
* der `overlay`-Trick (Spieler läuft hinter Häusern) geht verloren

Für ein echtes Spiel ist der Tilemap-Weg der bessere.
