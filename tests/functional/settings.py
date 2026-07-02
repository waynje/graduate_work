import os

from pydantic_settings import BaseSettings


class TestSettings(BaseSettings):
    es_host: str = os.getenv('ES_HOST', 'http://127.0.0.1:9200')
    es_index: str = 'movies'
    es_id_field: str = 'id'
    es_index_mapping: dict = {
        'mappings': {
            'dynamic': 'strict',
            'properties': {
                'id': {'type': 'keyword'},
                'imdb_rating': {'type': 'float'},
                'title': {'type': 'text'},
                'description': {'type': 'text'},
                'genre': {'type': 'keyword'},
                'director': {'type': 'text'},
                'created_at': {'type': 'date'},
                'updated_at': {'type': 'date'},
                'film_work_type': {'type': 'keyword'},
                'creation_date': {'type': 'date'},
                'type': {'type': 'keyword'},
                'created': {'type': 'date'},
                'modified': {'type': 'date'},
                'genres': {'type': 'keyword'},
                'genre_ids': {'type': 'keyword'},
                'directors_names': {'type': 'text'},
                'actors_names': {'type': 'text'},
                'writers_names': {'type': 'text'},
                'directors': {
                    'type': 'nested',
                    'properties': {
                        'id': {'type': 'keyword'},
                        'name': {'type': 'text'}
                    }
                },
                'actors': {
                    'type': 'nested',
                    'properties': {
                        'id': {'type': 'keyword'},
                        'name': {'type': 'text'}
                    }
                },
                'writers': {
                    'type': 'nested',
                    'properties': {
                        'id': {'type': 'keyword'},
                        'name': {'type': 'text'}
                    }
                }
            }
        }
    }


    redis_host: str = 'redis'
    service_url: str = os.getenv('SERVICE_URL', 'http://127.0.0.1:8000')
 

test_settings = TestSettings()