// Bringt eine generierte Zone nach Unity: Kollision aus der Maske und
// Monsterlager aus der Metadatei.
//
// Ablage:  Assets/Scripts/ZoneImport.cs
// Anleitung: docs/unity_import.md
//
// Massstab: Pixels Per Unit = 32 setzen, dann ist 1 Tile = 1 Unity-Unit.
// Tiled zaehlt y nach UNTEN, Unity nach OBEN — deshalb ueberall -y.

using System;
using UnityEngine;
using UnityEngine.Tilemaps;

// ---------------------------------------------------------------- Daten ----
// Feldnamen muessen exakt zum JSON passen, JsonUtility mappt nach Namen.

[Serializable]
public class ZoneCamp
{
    public int x;
    public int y;
    public float r;
    public string tier;     // "kern" = dichtes Jagdrevier, "rand" = ruhiger
    public string type;     // banditen | untote | bestien | spinnen | ruine
}

[Serializable]
public class ZonePoint
{
    public int x;
    public int y;
}

[Serializable]
public class ZoneArena
{
    public int x;
    public int y;
    public float r;
    public float[] lane_angles_rad;   // die vier Zugaenge
}

[Serializable]
public class ZoneMeta
{
    public string name;
    public int width_tiles;
    public int height_tiles;
    public int tile_size;
    public ZoneCamp[] camps;
    public ZoneArena arena;
    public ZonePoint town;
    public ZonePoint[] bridges;
    public ZonePoint[] cores;
}

public static class ZoneCoords
{
    /// Tile-Koordinate -> Weltposition (Mitte des Feldes), PPU = tile_size.
    public static Vector3 TileToWorld(int x, int y)
    {
        return new Vector3(x + 0.5f, -(y + 0.5f), 0f);
    }

    /// Tile-Koordinate -> Zelle einer Tilemap, die von oben nach unten laeuft.
    public static Vector3Int TileToCell(int x, int y)
    {
        return new Vector3Int(x, -y - 1, 0);
    }
}

// ----------------------------------------------------------- Kollision ----

/// Baut aus <name>_collision.png eine Kollisions-Tilemap.
/// Weiss = blockiert. Die Textur braucht "Read/Write Enabled" im Importer.
public class ZoneCollisionBuilder : MonoBehaviour
{
    public Texture2D collisionMask;
    public Tilemap targetTilemap;
    public TileBase blockTile;       // beliebiges Tile, wird nicht gerendert

    [ContextMenu("Kollision aufbauen")]
    public void Build()
    {
        if (collisionMask == null || targetTilemap == null || blockTile == null)
        {
            Debug.LogError("ZoneCollisionBuilder: Maske, Tilemap oder Tile fehlt.");
            return;
        }
        if (!collisionMask.isReadable)
        {
            Debug.LogError("ZoneCollisionBuilder: 'Read/Write Enabled' in den "
                           + "Import-Einstellungen der Maske aktivieren.");
            return;
        }

        targetTilemap.ClearAllTiles();
        int w = collisionMask.width, h = collisionMask.height;
        Color32[] px = collisionMask.GetPixels32();

        int blocked = 0;
        for (int y = 0; y < h; y++)
        {
            // GetPixels32 liefert Zeile 0 UNTEN, die PNG-Zeile 0 ist aber oben
            int row = h - 1 - y;
            for (int x = 0; x < w; x++)
            {
                if (px[row * w + x].r < 128) continue;
                targetTilemap.SetTile(ZoneCoords.TileToCell(x, y), blockTile);
                blocked++;
            }
        }
        Debug.Log($"Kollision aufgebaut: {blocked} von {w * h} Feldern blockiert.");
    }
}

// -------------------------------------------------------------- Spawns ----

/// Setzt pro Lager einen Spawn-Punkt. Der Radius aus der Metadatei ist der
/// Bereich, in dem die Gruppe patrouillieren darf.
public class ZoneSpawner : MonoBehaviour
{
    [Tooltip("<name>_meta.json als TextAsset hierher ziehen")]
    public TextAsset metaJson;

    [Serializable]
    public class TypePrefab
    {
        public string type;          // banditen | untote | bestien | spinnen | ruine
        public GameObject prefab;
        public int countKern = 6;    // Dichte im Jagdrevier
        public int countRand = 3;    // Dichte am Rand
    }

    public TypePrefab[] prefabs;
    public Transform parent;

    ZoneMeta meta;

    void Awake()
    {
        if (metaJson == null)
        {
            Debug.LogError("ZoneSpawner: metaJson fehlt.");
            return;
        }
        meta = JsonUtility.FromJson<ZoneMeta>(metaJson.text);
        SpawnAll();
    }

    public void SpawnAll()
    {
        if (meta == null || meta.camps == null) return;
        var root = parent != null ? parent : transform;

        foreach (var camp in meta.camps)
        {
            var entry = Array.Find(prefabs, p => p.type == camp.type);
            if (entry == null || entry.prefab == null) continue;

            int n = camp.tier == "kern" ? entry.countKern : entry.countRand;
            Vector3 center = ZoneCoords.TileToWorld(camp.x, camp.y);

            for (int i = 0; i < n; i++)
            {
                // gleichmaessig in der Kreisflaeche, nicht am Rand geballt
                float ang = UnityEngine.Random.value * Mathf.PI * 2f;
                float dist = camp.r * Mathf.Sqrt(UnityEngine.Random.value) * 0.85f;
                Vector3 pos = center + new Vector3(Mathf.Cos(ang) * dist,
                                                   Mathf.Sin(ang) * dist, 0f);
                Instantiate(entry.prefab, pos, Quaternion.identity, root);
            }
        }
        Debug.Log($"ZoneSpawner: {meta.camps.Length} Lager bestueckt.");
    }

    void OnDrawGizmosSelected()
    {
        if (metaJson == null) return;
        var m = JsonUtility.FromJson<ZoneMeta>(metaJson.text);
        if (m == null || m.camps == null) return;

        foreach (var c in m.camps)
        {
            Gizmos.color = c.tier == "kern"
                ? new Color(1f, 0.35f, 0.2f, 0.9f)
                : new Color(0.4f, 0.8f, 1f, 0.7f);
            Gizmos.DrawWireSphere(ZoneCoords.TileToWorld(c.x, c.y), c.r);
        }
        if (m.arena != null)
        {
            Gizmos.color = Color.yellow;
            Gizmos.DrawWireSphere(ZoneCoords.TileToWorld(m.arena.x, m.arena.y),
                                  m.arena.r);
        }
    }
}
