# StarBridge v0.1.0

Initial public release of StarBridge.

## Highlights

- Unified Windows GUI app (`StarBridge.exe`)
  - Start/Stop home agent
  - Generate config profiles
  - Profile list + copy URI
  - Network status panel (adapters, routes, path tests)
- CLI modes:
  - `relay`
  - `home-agent`
  - `socks-client`
  - `generate-configs`
- Dual-link support via bind IP:
  - `--relay-bind-host`
  - `--egress-bind-host`
- Dark UI theme
- Project docs + MIT license + CI compile check

## Release Asset

- `StarBridge-v0.1.0-win64.zip`
  - `StarBridge.exe`
  - `SHA256SUMS.txt`

## SHA256

`StarBridge.exe`:

`4efd1a74d490a5349f5bf0a0315c96fce6c1268c5c40c6815b6d2b9111286f9f`

## Notes

- `--no-tls` is for testing only.
- Enable TLS for real deployment.
