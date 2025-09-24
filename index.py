from fastapi import FastAPI, Request, HTTPException
import requests
import json
import uvicorn

app = FastAPI()

# Definições da API
TMDB_API_KEY = "6360eb433f3020d94a5de4f0fb52c720"

# Definições da IPTV
IPTV_URL = "http://sinalprivado.info/player_api.php"
IPTV_USER = "430214"
IPTV_PASS = "430214"

# Funções de suporte
def curl_get_json(url):
    try:
        response = requests.get(url)
        response.raise_for_status() # Lança um erro para status de erro (4xx ou 5xx)
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Erro na requisição: {e}")
        return None

def format_runtime(minutes):
    if not minutes:
        return "0min"
    h = minutes // 60
    m = minutes % 60
    return (f"{h}h " if h > 0 else "") + (f"{m}min" if m > 0 else "0min")

def get_tmdb_details(tmdb_id, api_key):
    url = f"https://api.themoviedb.org/3/movie/{tmdb_id}?api_key={api_key}&language=pt-BR&append_to_response=credits,videos,release_dates"
    return curl_get_json(url)

def get_iptv_list(iptv_url, iptv_user, iptv_pass):
    url = f"{iptv_url}?username={iptv_user}&password={iptv_pass}&action=get_vod_streams"
    return curl_get_json(url)

def find_best_match(title, iptv_list):
    best_match = None
    best_percent = 0
    for item in iptv_list:
        if 'name' in item and isinstance(item['name'], str):
            from difflib import SequenceMatcher
            percent = SequenceMatcher(None, title.lower(), item['name'].lower()).ratio() * 100
            
            if percent > best_percent:
                best_percent = percent
                best_match = item
    
    return best_match if best_percent >= 60 else None

def get_classification(details):
    release_dates = details.get('release_dates', {})
    if release_dates and 'results' in release_dates:
        for release in release_dates['results']:
            if release['iso_3166_1'] in ['BR', 'US']:
                for r in release.get('release_dates', []):
                    if 'certification' in r and r['certification']:
                        return r['certification']
    return ""

# Rota principal da API
@app.get("/")
async def get_movie_details(request: Request):
    tmdb_id = request.query_params.get('tmdb_id')
    
    if not tmdb_id:
        raise HTTPException(
            status_code=400,
            detail={
                "success": False,
                "message": "Parâmetro obrigatório ausente (tmdb_id)"
            }
        )

    details = get_tmdb_details(tmdb_id, TMDB_API_KEY)
    if not details or 'id' not in details:
        raise HTTPException(
            status_code=404,
            detail={
                "success": False,
                "message": "Filme não encontrado no TMDb"
            }
        )

    iptv_list = get_iptv_list(IPTV_URL, IPTV_USER, IPTV_PASS)
    iptv_data = find_best_match(details.get('title', ''), iptv_list) if iptv_list else None

    trailer = ""
    for video in details.get('videos', {}).get('results', []):
        if video.get('type') == 'Trailer' and video.get('key'):
            trailer = f"https://www.youtube.com/watch?v={video['key']}"
            break

    response = {
        "success": bool(iptv_data),
        "tmdb_id": details.get('id'),
        "titulo": details.get('title', ""),
        "titulo_original": details.get('original_title', ""),
        "sinopse": details.get('overview', "Descrição não disponível"),
        "nota": details.get('vote_average', 0),
        "lancamento": details.get('release_date', ""),
        "duracao": details.get('runtime', 0),
        "duracao_formatada": format_runtime(details.get('runtime', 0)),
        "classificacao_indicativa": get_classification(details),
        "poster": f"https://image.tmdb.org/t/p/w500{details['poster_path']}" if details.get('poster_path') else "",
        "backdrop": f"https://image.tmdb.org/t/p/w500{details['backdrop_path']}" if details.get('backdrop_path') else "",
        "trailer": trailer,
        "generos": [g['name'] for g in details.get('genres', [])],
        "elenco": [
            {"name": c.get('name', ""), "foto": f"https://image.tmdb.org/t/p/w200{c['profile_path']}" if c.get('profile_path') else ""}
            for c in details.get('credits', {}).get('cast', [])[:10]
        ],
    }

    if iptv_data:
        response['iptv_stream_id'] = iptv_data.get('stream_id')
        response['iptv_name'] = iptv_data.get('name')
        response['iptv_category_id'] = iptv_data.get('category_id', "")
        response['iptv_poster'] = iptv_data.get('stream_icon', "")
        response['iptv_stream_url'] = f"http://sinalprivado.info:80/movie/{IPTV_USER}/{IPTV_PASS}/{iptv_data.get('stream_id')}.mp4"
    else:
        response['message'] = "Não disponível no momento"

    return response
