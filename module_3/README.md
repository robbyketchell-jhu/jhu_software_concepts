### Run Postgres
```sh
docker run -d --name pg \
  -e POSTGRES_PASSWORD=postgres \
  -p 5432:5432 \
  -v pgdata:/var/lib/postgresql/data \
  postgres:17
```

### Run load_data.py
```sh
python load_data.py
```

