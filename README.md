# myrmm — agent e server MCP

Codice dell'agent (Go) e del server MCP (Go, con una versione equivalente in Python) di **myrmm**, un RMM personale. Il **server** (console, API, database) **non** è in questo repository.

- `agent/` — l'agent per Windows, Linux e macOS: servizio, check-in, esecuzione di job firmati, inventario, tunnel, sonde di rete.
- `mcp/go/` — il server MCP: un eseguibile statico senza dipendenze. `mcp/myrmm_mcp.py` è la versione equivalente in Python.
- `ci/` — prove: parità tra le due versioni dell'MCP e controllo dei segreti.

## Compilare

```
cd agent  && go build -trimpath -ldflags "-s -w" -o myrmm-agent .
cd mcp/go && go build -trimpath -ldflags "-s -w" -o myrmm-mcp .
```
`CGO_ENABLED=0` con `GOOS` e `GOARCH` per le altre piattaforme (windows/amd64, linux/amd64+arm64, darwin/amd64+arm64). Serve Go 1.24.

## Provare

```
cd agent && go vet ./... && go test ./...
python3 ci/mcp_go_parity_test.py
python3 ci/scan_secrets_test.py && python3 ci/scan_secrets.py . --allow-path ci/scan_secrets_test.py
```
Il workflow `Test` fa la stessa cosa su Ubuntu, Windows (2022 e 2025) e macOS (Apple Silicon e Intel).

## Configurazione dell'agent

Vedi `agent/config.example.json`: `server_url`, `enroll_token` e `job_signing_key` vengono dal tuo server. Non committare mai i valori veri.

## Licenza

Proprietaria, tutti i diritti riservati: vedi `LICENSE`. Il codice è visibile solo per la verifica automatica; non è open source e non se ne autorizza l'uso.

## Sicurezza

Vedi `SECURITY.md`.
