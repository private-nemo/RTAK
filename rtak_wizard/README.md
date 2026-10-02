# RTAK Setup Wizard

The setup wizard has moved to its own repository:

**[github.com/private-nemo/mesh-config-wizard](https://github.com/private-nemo/mesh-config-wizard)**

---

## What it does

Browser-based setup wizard — no dependencies beyond Python 3 stdlib. Covers both RTAK OmniNode and mesh_babelfish configuration.

**RTAK flow:** hardware variant → radio ports → RF settings → optional services → operators → generates setup command, Reticulum config, Partyline config, cert commands, and passwords.

**BabelFish flow:** protocol selection → port assignments → session settings → generates complete `config.yaml`.

## Quick start

```bash
git clone https://github.com/private-nemo/mesh-config-wizard
cd mesh-config-wizard
python3 wizard.py
```

Opens a browser automatically. Also accessible from any device on the same network at `http://<host-ip>:5000/`.
