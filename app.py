#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, math, json, threading, time, io, requests
from datetime import datetime
from collections import defaultdict

import osmium
from flask import Flask, jsonify, send_file, Response

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

PBF_URL = 'https://download.geofabrik.de/europe/czech-republic-latest.osm.pbf'
PBF_FILE = 'highways.osm.pbf'
SURFACE_JSON_FILE = 'surface_stats_cz.json'
LIT_JSON_FILE = 'lit_stats_cz.json'
SURFACE_GRAPH_FILE = 'surface_stats_cz.png'
LIT_GRAPH_FILE = 'lit_stats_cz.png'
UPDATE_INTERVAL = 10800  # 3 hodiny

# ------------------- Funkce pro Haversine -------------------
def haversine(lat1, lon1, lat2, lon2):
    R = 6371000.0  # poloměr Země v metrech
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    c = 2*math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

# ------------------- Handler pro osmium -------------------
class SurfaceHandler(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.surface_length = defaultdict(float)
        self.lit_length = defaultdict(float)

    def way(self, w):
        # ANALYZUJEME JEN WAY S HIGHWAY
        if 'highway' not in w.tags:
            return
        if not w.nodes:
            return
        coords = [(n.lat, n.lon) for n in w.nodes if n.location.valid()]
        if len(coords) < 2:
            return
        total_len = 0
        for (lat1, lon1), (lat2, lon2) in zip(coords, coords[1:]):
            total_len += haversine(lat1, lon1, lat2, lon2)
        
        # Statistiky pro surface
        surface = w.tags.get('surface', 'unknown')
        self.surface_length[surface] += total_len / 1000  # převod na km
        
        # Statistiky pro lit
        lit = w.tags.get('lit', 'undefined')
        if lit.lower() == 'yes':
            lit = 'yes'
        elif lit.lower() == 'no':
            lit = 'no'
        else:
            lit = 'other' if lit != 'undefined' else 'undefined'
        self.lit_length[lit] += total_len / 1000

# ------------------- Funkce pro stažení souboru -------------------
def download_pbf():
    print("Stahuji PBF soubor...")
    r = requests.get(PBF_URL, stream=True)
    with open(PBF_FILE, 'wb') as f:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)
    print("Staženo.")

# ------------------- Pomocné funkce pro analýzu -------------------
def process_stats(data_dict, stats_type="Povrchy"):
    """Zpracuje data a vrátí seřazený seznam s procenty"""
    data_sorted = dict(sorted(data_dict.items(), key=lambda x: x[1], reverse=True))
    total_km = sum(data_sorted.values())
    result = []
    for key, km in data_sorted.items():
        result.append({
            'type': key,
            'km': round(km, 2),
            'percent': round(km / total_km * 100, 2)
        })
    return result, total_km

def create_graph(data, graph_file, title, color_scheme='viridis'):
    """Vytvoří graf a uloží ho do souboru"""
    plt.figure(figsize=(12, 7))
    
    names = [x['type'] for x in data[:20]]
    values = [x['km'] for x in data[:20]]
    
    # Log osa nesnáší nuly – pojistka
    values = [max(v, 0.001) for v in values]
    
    # Barvy podle schématu
    colors = plt.cm.get_cmap(color_scheme)(np.linspace(0.2, 0.8, len(names)))
    
    bars = plt.barh(names[::-1], values[::-1], color=colors[::-1])
    
    # Přidání hodnot na sloupce
    for bar in bars:
        width = bar.get_width()
        plt.text(width + (max(values) * 0.01), bar.get_y() + bar.get_height()/2,
                f'{width:.1f} km', ha='left', va='center', fontsize=9)
    
    # LOG2 osa
    plt.xscale("log", base=2)
    plt.xlabel("Délka v km (log₂ škála)")
    
    # Mřížka jen na ose X, jemná a nenásilná
    plt.grid(axis="x", which="both", linestyle="--", alpha=0.5)
    
    plt.title(title, fontsize=14, fontweight='bold')
    plt.tight_layout()
    plt.savefig(graph_file, dpi=150, bbox_inches='tight')
    plt.close()

# ------------------- Funkce pro analýzu -------------------
def analyze():
    if not os.path.exists(PBF_FILE):
        download_pbf()
    print(f"{datetime.now()} - Spouštím analýzu...")
    handler = SurfaceHandler()
    handler.apply_file(PBF_FILE, locations=True)
    
    # Zpracování statistik pro surface
    surface_data, surface_total_km = process_stats(handler.surface_length, "Povrchy")
    
    # Uložit JSON pro surface
    with open(SURFACE_JSON_FILE, 'w', encoding='utf-8') as f:
        json.dump({
            'last_updated': datetime.now().isoformat(), 
            'total_km': round(surface_total_km, 2),
            'data': surface_data
        }, f, ensure_ascii=False, indent=2)
    
    # Zpracování statistik pro lit
    lit_data, lit_total_km = process_stats(handler.lit_length, "Osvětlení")
    
    # Uložit JSON pro lit
    with open(LIT_JSON_FILE, 'w', encoding='utf-8') as f:
        json.dump({
            'last_updated': datetime.now().isoformat(), 
            'total_km': round(lit_total_km, 2),
            'data': lit_data
        }, f, ensure_ascii=False, indent=2)
    
    # Vytvořit grafy
    import numpy as np
    
    # Graf pro surface
    create_graph(surface_data, SURFACE_GRAPH_FILE, "Top 20 povrchů cest v ČR (log₂ škála)", 'viridis')
    
    # Graf pro lit
    create_graph(lit_data, LIT_GRAPH_FILE, "Osvětlení cest v ČR (log₂ škála)", 'plasma')
    
    print(f"{datetime.now()} - Analýza dokončena. Celkem {surface_total_km:.2f} km.")

# ------------------- Funkce pro periodickou aktualizaci -------------------
def periodic_update():
    while True:
        try:
            analyze()
        except Exception as e:
            print("Chyba při analýze:", e)
        time.sleep(UPDATE_INTERVAL)

# ------------------- Flask server -------------------
app = Flask(__name__)

def generate_table(data, title):
    """Vygeneruje HTML tabulku z dat"""
    if not data:
        return f"<h3>{title}</h3><p>Data nejsou k dispozici.</p>"
    
    table_html = f"""
    <div class="stats-section">
        <h3>{title}</h3>
        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th>Typ</th>
                        <th>Délka (km)</th>
                        <th>Procento</th>
                    </tr>
                </thead>
                <tbody>
    """
    
    for row in data[:15]:  # Zobrazíme prvních 15 položek
        table_html += f"""
                    <tr>
                        <td>{row.get('type', row.get('surface', 'N/A'))}</td>
                        <td>{row['km']}</td>
                        <td>{row['percent']}%</td>
                    </tr>
        """
    
    table_html += """
                </tbody>
            </table>
        </div>
    </div>
    """
    return table_html

@app.route('/')
def index():
    # Načtení dat pro surface
    surface_stats = {}
    if os.path.exists(SURFACE_JSON_FILE):
        with open(SURFACE_JSON_FILE, 'r', encoding='utf-8') as f:
            surface_stats = json.load(f)
    
    # Načtení dat pro lit
    lit_stats = {}
    if os.path.exists(LIT_JSON_FILE):
        with open(LIT_JSON_FILE, 'r', encoding='utf-8') as f:
            lit_stats = json.load(f)
    
    last_updated = surface_stats.get('last_updated', lit_stats.get('last_updated', "ještě není dostupné"))
    surface_data = surface_stats.get('data', [])
    lit_data = lit_stats.get('data', [])
    
    # Jednoduché HTML + moderní responzivní CSS
    html = f"""
    <!DOCTYPE html>
    <html lang="cs">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Statistika cest v ČR - OpenStreetMap</title>
        <style>
            * {{
                box-sizing: border-box;
                margin: 0;
                padding: 0;
            }}
            
            body {{
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                line-height: 1.6;
                color: #333;
                background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
                min-height: 100vh;
                padding: 20px;
            }}
            
            .container {{
                max-width: 1400px;
                margin: 0 auto;
                background: white;
                border-radius: 20px;
                box-shadow: 0 15px 35px rgba(50, 50, 93, 0.1), 0 5px 15px rgba(0, 0, 0, 0.07);
                overflow: hidden;
                padding: 30px;
            }}
            
            header {{
                text-align: center;
                margin-bottom: 40px;
                padding-bottom: 20px;
                border-bottom: 2px solid #eaeaea;
            }}
            
            h1 {{
                color: #2c3e50;
                font-size: 2.8rem;
                margin-bottom: 15px;
                background: linear-gradient(90deg, #3498db, #2c3e50);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
            }}
            
            h2 {{
                color: #3498db;
                margin: 30px 0 20px;
                padding-bottom: 10px;
                border-bottom: 2px solid #3498db;
            }}
            
            h3 {{
                color: #2c3e50;
                margin: 25px 0 15px;
                font-size: 1.5rem;
            }}
            
            .stats-grid {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(500px, 1fr));
                gap: 30px;
                margin-bottom: 40px;
            }}
            
            @media (max-width: 1100px) {{
                .stats-grid {{
                    grid-template-columns: 1fr;
                }}
            }}
            
            .stats-section {{
                background: #f8f9fa;
                border-radius: 15px;
                padding: 25px;
                box-shadow: 0 5px 15px rgba(0, 0, 0, 0.05);
                transition: transform 0.3s ease;
            }}
            
            .stats-section:hover {{
                transform: translateY(-5px);
            }}
            
            .table-container {{
                overflow-x: auto;
                margin-top: 15px;
            }}
            
            table {{
                width: 100%;
                border-collapse: collapse;
                margin-top: 10px;
            }}
            
            th {{
                background: linear-gradient(90deg, #3498db, #2980b9);
                color: white;
                font-weight: 600;
                padding: 15px 12px;
                text-align: left;
                position: sticky;
                top: 0;
            }}
            
            td {{
                padding: 12px;
                border-bottom: 1px solid #eaeaea;
            }}
            
            tr:nth-child(even) {{
                background-color: #f8f9fa;
            }}
            
            tr:hover {{
                background-color: #e8f4fc;
                transition: background-color 0.2s;
            }}
            
            .graph-container {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(600px, 1fr));
                gap: 30px;
                margin: 40px 0;
            }}
            
            @media (max-width: 768px) {{
                .graph-container {{
                    grid-template-columns: 1fr;
                }}
            }}
            
            .graph-box {{
                background: white;
                border-radius: 15px;
                padding: 20px;
                box-shadow: 0 5px 15px rgba(0, 0, 0, 0.08);
            }}
            
            .graph-box img {{
                width: 100%;
                height: auto;
                border-radius: 10px;
                border: 1px solid #eaeaea;
            }}
            
            .api-section {{
                background: #f8f9fa;
                border-radius: 15px;
                padding: 25px;
                margin-top: 40px;
            }}
            
            .api-grid {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
                gap: 20px;
                margin-top: 20px;
            }}
            
            .api-endpoint {{
                background: white;
                padding: 20px;
                border-radius: 10px;
                box-shadow: 0 3px 10px rgba(0, 0, 0, 0.08);
                border-left: 4px solid #3498db;
            }}
            
            .api-endpoint h4 {{
                color: #2c3e50;
                margin-bottom: 10px;
            }}
            
            .api-endpoint a {{
                color: #3498db;
                text-decoration: none;
                font-weight: 500;
                display: block;
                margin: 8px 0;
                word-break: break-all;
            }}
            
            .api-endpoint a:hover {{
                text-decoration: underline;
            }}
            
            .api-endpoint small {{
                color: #7f8c8d;
                font-size: 0.9rem;
                line-height: 1.4;
            }}
            
            .info-box {{
                background: linear-gradient(135deg, #e3f2fd, #bbdefb);
                border-radius: 12px;
                padding: 20px;
                margin: 25px 0;
                border-left: 5px solid #2196f3;
            }}
            
            .update-info {{
                background: #e8f5e9;
                color: #2e7d32;
                padding: 15px;
                border-radius: 10px;
                margin: 20px 0;
                display: flex;
                align-items: center;
                gap: 10px;
            }}
            
            .update-info:before {{
                content: "🔄";
                font-size: 1.2rem;
            }}
            
            footer {{
                text-align: center;
                margin-top: 50px;
                padding-top: 20px;
                border-top: 1px solid #eaeaea;
                color: #7f8c8d;
                font-size: 0.9rem;
            }}
            
            a {{
                color: #3498db;
                text-decoration: none;
                transition: color 0.2s;
            }}
            
            a:hover {{
                color: #2980b9;
            }}
            
            .tag {{
                display: inline-block;
                background: #e3f2fd;
                color: #1976d2;
                padding: 4px 10px;
                border-radius: 20px;
                font-size: 0.85rem;
                margin: 2px;
            }}
            
            @media (max-width: 768px) {{
                .container {{
                    padding: 15px;
                }}
                
                h1 {{
                    font-size: 2rem;
                }}
                
                .stats-grid {{
                    grid-template-columns: 1fr;
                }}
                
                .graph-container {{
                    grid-template-columns: 1fr;
                }}
            }}
            
            @media print {{
                .container {{
                    box-shadow: none;
                }}
                
                .stats-section:hover {{
                    transform: none;
                }}
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <header>
                <h1>📊 Statistika cest v ČR</h1>
                <p>Analýza dat z OpenStreetMap - povrchy a osvětlení komunikací</p>
                <div class="update-info">
                    <strong>Poslední aktualizace:</strong> {last_updated}
                </div>
            </header>
            
            <div class="info-box">
                <p>Tato data jsou k dispozici pod otevřenou licencí <strong>Open Data Commons Open Database License (ODbL)</strong>.</p>
                <p>Data pocházejí z <a href="https://www.openstreetmap.org/copyright" target="_blank">OpenStreetMap</a> a jsou aktualizována každé 3 hodiny.</p>
                <p>Analyzujeme komunikace s tagem <span class="tag">highway=*</span> a kategorizujeme podle <span class="tag">surface</span> a <span class="tag">lit</span>.</p>
            </div>
            
            <h2>📈 Statistiky podle typu</h2>
            <div class="stats-grid">
                {generate_table(surface_data, "🗺️ Povrchy cest")}
                {generate_table(lit_data, "💡 Osvětlení cest")}
            </div>
            
            <h2>📊 Grafy</h2>
            <div class="graph-container">
                <div class="graph-box">
                    <h3>Povrchy cest (log₂ škála)</h3>
                    <img src="/graph/surface" alt="Graf povrchů cest">
                </div>
                <div class="graph-box">
                    <h3>Osvětlení cest (log₂ škála)</h3>
                    <img src="/graph/lit" alt="Graf osvětlení cest">
                </div>
            </div>
            
            <div class="api-section">
                <h2>🔌 API pro vývojáře</h2>
                <p>Tato služba poskytuje otevřené REST API pro další zpracování dat:</p>
                
                <div class="api-grid">
                    <div class="api-endpoint">
                        <h4>Status služby</h4>
                        <a href="/api/status">/api/status</a>
                        <small>Základní informace o stavu API a čase poslední aktualizace.</small>
                    </div>
                    
                    <div class="api-endpoint">
                        <h4>Všechny povrchy</h4>
                        <a href="/api/surfaces">/api/surfaces</a>
                        <small>Kompletní statistika povrchů cest v ČR.</small>
                    </div>
                    
                    <div class="api-endpoint">
                        <h4>Všechna osvětlení</h4>
                        <a href="/api/lit">/api/lit</a>
                        <small>Kompletní statistika osvětlení cest v ČR.</small>
                    </div>
                    
                    <div class="api-endpoint">
                        <h4>Top 10 povrchů</h4>
                        <a href="/api/surfaces/top/10">/api/surfaces/top/10</a>
                        <small>Nejpoužívanější povrchy podle celkové délky.</small>
                    </div>
                    
                    <div class="api-endpoint">
                        <h4>Detail povrchu</h4>
                        <code>/api/surfaces/&lt;surface&gt;</code>
                        <small>Příklad: <a href="/api/surfaces/asphalt">/api/surfaces/asphalt</a></small>
                    </div>
                    
                    <div class="api-endpoint">
                        <h4>Čistá JSON data</h4>
                        <a href="/data/surface.json">/data/surface.json</a><br>
                        <a href="/data/lit.json">/data/lit.json</a>
                        <small>Surová data ke stažení.</small>
                    </div>
                </div>
            </div>
            
            <footer>
                <p>© {datetime.now().year} | Data z <a href="https://www.openstreetmap.org" target="_blank">OpenStreetMap</a> | 
                Zdrojový kód na <a href="https://github.com" target="_blank">GitHub</a></p>
                <p>Aktualizace každé 3 hodiny | Powered by Flask & Osmium</p>
            </footer>
        </div>
    </body>
    </html>
    """
    return html

@app.route('/graph/surface')
def graph_surface():
    if os.path.exists(SURFACE_GRAPH_FILE):
        return send_file(SURFACE_GRAPH_FILE, mimetype='image/png')
    return Response("Graf povrchů není k dispozici.", status=404)

@app.route('/graph/lit')
def graph_lit():
    if os.path.exists(LIT_GRAPH_FILE):
        return send_file(LIT_GRAPH_FILE, mimetype='image/png')
    return Response("Graf osvětlení není k dispozici.", status=404)

@app.route('/data/surface.json')
def data_surface_json():
    if os.path.exists(SURFACE_JSON_FILE):
        return send_file(SURFACE_JSON_FILE, mimetype='application/json')
    return Response("Data pro povrchy nejsou k dispozici.", status=404)

@app.route('/data/lit.json')
def data_lit_json():
    if os.path.exists(LIT_JSON_FILE):
        return send_file(LIT_JSON_FILE, mimetype='application/json')
    return Response("Data pro osvětlení nejsou k dispozici.", status=404)

@app.route('/api/status')
def api_status():
    last_updated = None
    if os.path.exists(SURFACE_JSON_FILE):
        with open(SURFACE_JSON_FILE, 'r', encoding='utf-8') as f:
            stats = json.load(f)
            last_updated = stats.get('last_updated')

    return jsonify({
        "status": "ok",
        "last_updated": last_updated,
        "update_interval_seconds": UPDATE_INTERVAL,
        "endpoints": {
            "surface": "/api/surfaces",
            "lit": "/api/lit",
            "graphs": {
                "surface": "/graph/surface",
                "lit": "/graph/lit"
            }
        }
    })

@app.route('/api/surfaces')
def api_surfaces():
    if not os.path.exists(SURFACE_JSON_FILE):
        return jsonify({"error": "data not available"}), 503

    with open(SURFACE_JSON_FILE, 'r', encoding='utf-8') as f:
        stats = json.load(f)

    return jsonify(stats)

@app.route('/api/lit')
def api_lit():
    if not os.path.exists(LIT_JSON_FILE):
        return jsonify({"error": "data not available"}), 503

    with open(LIT_JSON_FILE, 'r', encoding='utf-8') as f:
        stats = json.load(f)

    return jsonify(stats)

@app.route('/api/surfaces/top/<int:n>')
def api_surfaces_top(n):
    if not os.path.exists(SURFACE_JSON_FILE):
        return jsonify({"error": "data not available"}), 503

    with open(SURFACE_JSON_FILE, 'r', encoding='utf-8') as f:
        stats = json.load(f)

    return jsonify({
        "top": n,
        "data": stats["data"][:n]
    })

@app.route('/api/lit/top/<int:n>')
def api_lit_top(n):
    if not os.path.exists(LIT_JSON_FILE):
        return jsonify({"error": "data not available"}), 503

    with open(LIT_JSON_FILE, 'r', encoding='utf-8') as f:
        stats = json.load(f)

    return jsonify({
        "top": n,
        "data": stats["data"][:n]
    })

@app.route('/api/surfaces/<surface>')
def api_surface_detail(surface):
    if not os.path.exists(SURFACE_JSON_FILE):
        return jsonify({"error": "data not available"}), 503

    with open(SURFACE_JSON_FILE, 'r', encoding='utf-8') as f:
        stats = json.load(f)

    for row in stats["data"]:
        if row["type"] == surface:
            return jsonify(row)

    return jsonify({"error": "surface not found"}), 404

@app.route('/api/lit/<lit_type>')
def api_lit_detail(lit_type):
    if not os.path.exists(LIT_JSON_FILE):
        return jsonify({"error": "data not available"}), 503

    with open(LIT_JSON_FILE, 'r', encoding='utf-8') as f:
        stats = json.load(f)

    for row in stats["data"]:
        if row["type"] == lit_type:
            return jsonify(row)

    return jsonify({"error": "lit type not found"}), 404

# ------------------- Spuštění -------------------
if __name__ == "__main__":
    # Import numpy pro grafy
    import numpy as np
    
    # Analýza hned při startu
    analyze()
    # Start periodické aktualizace na pozadí
    threading.Thread(target=periodic_update, daemon=True).start()
    # Spustit Flask server na portu 5000
    app.run(host='0.0.0.0', port=9918, debug=False)