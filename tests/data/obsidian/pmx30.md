# pmx30 · Proxmox VE (Testserver)

- **IP:** 192.0.2.99 · WebUI `https://192.0.2.99:8006/` · SSH `root@192.0.2.99`
- **Version:** pve-manager 9.2.x
- **Platten:** 2× Testplatte 256 GB
- **Doku**: siehe [[Dienste/testdienst|Testdienst]]
  - **Unterpunkt:** wird ignoriert

## Platten

| Label | Seriennummer | Rolle |
|---|---|---|
| SSD-1 | 111111274913 | `rpool` Spiegel |
| SSD-2 | 222222274988 | `rpool` Spiegel |

## Gäste

| ID | Name | IP |
|:--|:--|--:|
| 101 | testvm | 192.0.2.101 |
| 102 | [[Dienste/testlxc\|testlxc]] | 192.0.2.102 |
| 103 | kurz |
