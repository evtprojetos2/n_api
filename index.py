from fastapi import FastAPI, Request, HTTPException
import requests
import json
import os
from difflib import SequenceMatcher

# ================== CONFIG ==================
TMDB_API_KEY = "6360eb433f3020d94a5de4f0fb52c720"
IPTV_DOMAIN  = "http://sinalprivado.info"
IPTV_USER    = "430214"
IPTV_PASS    = "430214"

# ================== APP ==================
app = FastAPI()

# ================== HELPERS ==================

# Função de Cache (Simplificada para ambiente Vercel)
# Nota: Em um ambiente serverless como o Vercel, o cache de arquivos em disco (como no PHP) não é persistente. 
# Para manter a simplicidade, o cache em memória ou um serviço externo (Redis, Memcached) é a melhor prática, 
# mas aqui faremos uma versão simples sem cache em disco para evitar problemas de permissão/persistência.
# Removendo a lógica de cache para focar na conversão da lógica principal.
def http_get_json(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; TMDB-IPTV/1.0)"}
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status() 
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Erro na requisição: {e}")
        return {"_error": str(e)}

def find_best_match(title, iptv_list, min_percent=70):
    best_match = None
    best_percent = 0
    for item in iptv_list:
        if 'name' in item and isinstance(item['name'], str):
            percent = SequenceMatcher(None, title.lower(), item['name'].lower()).ratio() * 100
            
            if percent > best_percent:
                best_percent = percent
                best_match = item
    
    return best_match if best_percent >= min_percent else None

# ================== ROTA DE FILMES (/movie) ==================

def get_movie_classification(details):
    release_dates = details.get('release_dates', {})
    if release_dates and 'results' in release_dates:
        for release in release_dates['results']:
            if release['iso_3166_1'] in ['BR', 'US']:
                for r in release.get('release_dates', []):
                    if 'certification' in r and r['certification']:
                        return r['certification']
    return ""

def format_runtime(minutes):
    if not minutes:
        return "0min"
    h = minutes // 60
    m = minutes % 60
    return (f"{h}h " if h > 0 else "") + (f"{m}min" if m > 0 else "0min")

@app.get("/movie")
async def get_movie_details(request: Request):
    tmdb_id = request.query_params.get('tmdb_id')
    
    if not tmdb_id:
        raise HTTPException(
            status_code=400,
            detail={"success": False, "message": "Parâmetro obrigatório ausente (tmdb_id)"}
        )

    # 1. Busca no TMDb (Filme)
    tmdb_url = f"https://api.themoviedb.org/3/movie/{tmdb_id}?api_key={TMDB_API_KEY}&language=pt-BR&append_to_response=credits,videos,release_dates"
    details = http_get_json(tmdb_url)

    if details.get('_error') or 'id' not in details:
        raise HTTPException(
            status_code=404,
            detail={"success": False, "message": "Filme não encontrado no TMDb"}
        )

    # 2. Busca no IPTV (Filmes/VOD)
    iptv_vod_url = f"{IPTV_DOMAIN}/player_api.php?username={IPTV_USER}&password={IPTV_PASS}&action=get_vod_streams"
    iptv_list = http_get_json(iptv_vod_url)
    iptv_data = find_best_match(details.get('title', ''), iptv_list, min_percent=60) if not iptv_list.get('_error') else None

    # Trailer
    trailer = next((f"https://www.youtube.com/watch?v={v['key']}" 
                    for v in details.get('videos', {}).get('results', []) 
                    if v.get('type') == 'Trailer' and v.get('key')), "")

    # Monta resposta
    response = {
        "success": bool(iptv_data),
        "tmdb_id": details.get('id'),
        "titulo": details.get('title', ""),
        "sinopse": details.get('overview', "Descrição não disponível"),
        "nota": details.get('vote_average', 0),
        "lancamento": details.get('release_date', ""),
        "duracao_formatada": format_runtime(details.get('runtime', 0)),
        "classificacao_indicativa": get_movie_classification(details),
        "poster": f"https://image.tmdb.org/t/p/w500{details['poster_path']}" if details.get('poster_path') else "",
        "trailer": trailer,
        "generos": [g['name'] for g in details.get('genres', [])],
        "elenco": [
            {"name": c.get('name', ""), "foto": f"https://image.tmdb.org/t/p/w200{c['profile_path']}"}
            for c in details.get('credits', {}).get('cast', [])[:10] if c.get('profile_path')
        ],
    }

    if iptv_data:
        response['iptv_stream_id'] = iptv_data.get('stream_id')
        response['iptv_name'] = iptv_data.get('name')
        response['iptv_stream_url'] = f"{IPTV_DOMAIN}:80/movie/{IPTV_USER}/{IPTV_PASS}/{iptv_data.get('stream_id')}.mp4"
    else:
        response['message'] = "Filme não disponível no IPTV no momento"

    return response

# ================== ROTA DE SÉRIES (/series) ==================

def get_tv_classification(tmdb):
    ratings = tmdb.get('content_ratings', {}).get('results', [])
    for r in ratings:
        if r.get('iso_3166_1') in ['US', 'BR']:
            if r.get('rating'):
                return r['rating'].replace('TV-', '')
    return ""

@app.get("/series")
async def get_series_details(request: Request):
    tmdb_id = request.query_params.get('tmdb_id')
    
    if not tmdb_id:
        raise HTTPException(
            status_code=400,
            detail={"success": False, "message": "Parâmetro obrigatório ausente (tmdb_id)"}
        )

    # 1. Busca no TMDb (Série)
    tmdb_url = f"https://api.themoviedb.org/3/tv/{tmdb_id}?api_key={TMDB_API_KEY}&language=pt-BR&append_to_response=credits,videos,content_ratings"
    tmdb = http_get_json(tmdb_url)

    if tmdb.get('_error') or 'id' not in tmdb:
        raise HTTPException(
            status_code=404,
            detail={"success": False, "message": "Série não disponível no momento"}
        )

    # 2. Busca no IPTV (Lista de Séries)
    iptv_series_url = f"{IPTV_DOMAIN}/player_api.php?username={IPTV_USER}&password={IPTV_PASS}&action=get_series"
    iptv_series = http_get_json(iptv_series_url)

    iptv_match = find_best_match(tmdb.get('name', ''), iptv_series, min_percent=70)

    if not iptv_match:
        raise HTTPException(
            status_code=404,
            detail={"success": False, "message": "Série não disponível no momento no IPTV"}
        )

    # 3. Busca Informações da Série no IPTV (para episódios)
    iptv_info_url = f"{IPTV_DOMAIN}/player_api.php?username={IPTV_USER}&password={IPTV_PASS}&action=get_series_info&series_id={iptv_match['series_id']}"
    iptv_info = http_get_json(iptv_info_url)

    # Trailer
    trailer = next((f"https://www.youtube.com/watch?v={v['key']}" 
                    for v in tmdb.get('videos', {}).get('results', []) 
                    if v.get('type') == 'Trailer' and v.get('key')), "")

    # Monta a estrutura principal
    response = {
        "success": True,
        "serie": {
            "tmdb_id": tmdb.get('id', 0),
            "titulo": tmdb.get('name', ""),
            "sinopse": tmdb.get('overview', "Descrição não disponível"),
            "nota": tmdb.get('vote_average', 0),
            "lancamento": tmdb.get('first_air_date', ""),
            "poster": f"https://image.tmdb.org/t/p/w500{tmdb['poster_path']}" if tmdb.get('poster_path') else "",
            "backdrop": f"https://image.tmdb.org/t/p/w780{tmdb['backdrop_path']}" if tmdb.get('backdrop_path') else "",
            "trailer": trailer,
            "generos": [g['name'] for g in tmdb.get('genres', [])],
            "elenco": [
                {"name": c.get('name', ""), "foto": f"https://image.tmdb.org/t/p/w200{c['profile_path']}"}
                for c in tmdb.get('credits', {}).get('cast', [])[:10] if c.get('profile_path')
            ],
            "classificacao": get_tv_classification(tmdb),
        },
        "temporadas": [],
        "episodios": []
    }

    # Processa Temporadas e Episódios
    for season in tmdb.get('seasons', []):
        if season.get('season_number', 0) == 0: continue
        response['temporadas'].append({
            "season_number": season.get('season_number'),
            "name": season.get('name', ""),
            "poster": f"https://image.tmdb.org/t/p/w300{season['poster_path']}" if season.get('poster_path') else "",
            "episode_count": season.get('episode_count', 0),
            "air_date": season.get('air_date', "")
        })

    # Itera sobre temporadas do IPTV para obter episódios detalhados do TMDb
    for season_num, eps in iptv_info.get('episodes', {}).items():
        # Busca a temporada inteira do TMDb para evitar múltiplas chamadas por episódio
        tmdb_season_url = f"https://api.themoviedb.org/3/tv/{tmdb_id}/season/{season_num}?api_key={TMDB_API_KEY}&language=pt-BR"
        tmdb_season = http_get_json(tmdb_season_url)
        tmdb_episodes = {ep.get('episode_number'): ep for ep in tmdb_season.get('episodes', [])}

        for ep in eps:
            ep_num = ep.get('episode_num')
            tmdb_ep = tmdb_episodes.get(ep_num, {})
            
            # Monta o objeto de episódio
            response['episodios'].append({
                "season_number": season_num,
                "episode_number": ep_num,
                "title": tmdb_ep.get('name', ep.get('title', "")),
                "sinopse": tmdb_ep.get('overview', "Descrição não disponível"),
                "still_path": f"https://image.tmdb.org/t/p/w300{tmdb_ep['still_path']}" if tmdb_ep.get('still_path') else "",
                "air_date": tmdb_ep.get('air_date', ""),
                "nota": tmdb_ep.get('vote_average', 0),
                "iptv_url": f"{IPTV_DOMAIN}/series/{IPTV_USER}/{IPTV_PASS}/{ep.get('id')}.{ep.get('container_extension', 'mp4')}"
            })

    return response
