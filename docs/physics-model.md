# MCP Physics Model

## Particle definition

The custom EDepSim fork registers one stable MCP species:

| Property | Value |
|---|---|
| Name | `mcp` |
| PDG | `9000001` |
| Spin | 1/2 |
| Type | lepton |
| Runtime mass | `EDEPSIM_MCP_MASS_MEV` |
| Runtime charge | `EDEPSIM_MCP_CHARGE` |

Example:

```bash
export EDEPSIM_MCP_MASS_MEV=20.458
export EDEPSIM_MCP_CHARGE=0.3
```

Set these variables **before** launching `edep-sim`; Geant4 constructs the particle during initialization.

## Valid input domain

The current parser rejects:

- `mass <= 10 MeV`;
- `charge == 0`;
- malformed, overflowing, or non-finite values.

The mass restriction is a limitation of the current ionization-focused implementation, not a statement about physically allowed MCP masses.

## Geant4 processes

The current MCP receives:

```text
G4hMultipleScattering
G4hIonisation
```

It does not yet have dedicated implementations for:

- bremsstrahlung;
- pair production;
- separate single-Coulomb scattering;
- low-mass MCP ionization;
- sign-specific MCP/anti-MCP truth species.

!!! warning "Charge sign"
    A negative `EDEPSIM_MCP_CHARGE` changes the run-wide electric charge but does not create a separate antiparticle PDG code. Do not treat it as a complete MCP/anti-MCP model.

## Ionization mode

The controlled and realistic macros use:

```text
/edep/phys/ionizationModel 0
```

This avoids an EDepSim branch in which charge magnitude is used as a proxy for particle category. That categorization is conceptually unsafe for MCPs.

## Controlled validation results

### Unit-charge limit

A unit-charge MCP with the muon mass was compared with a standard muon on the same trajectory. Representative mean energy loss was:

```text
MCP q=1e   0.182497 MeV/mm
mu+        0.182481 MeV/mm
```

This confirmed that the custom particle behaves as expected in the ordinary charged-lepton limit.

### Charge scaling

At `q=0.3e`, the controlled sample gave approximately:

```text
0.0164092 MeV/mm
```

and:

```text
0.0164092 / 0.182497 ≈ 0.0899 ≈ (0.3)^2
```

A broader scan extended to about `q=0.01e` and preserved the expected approximate trend.

### Step-limiter threshold

EDepSim `ExtraPhysics` applies a step limiter only for:

```text
abs(charge) > 0.1
```

Therefore:

```text
q=0.11e  limiter active
q=0.10e  limiter inactive
q=0.09e  limiter inactive
```

No physical discontinuity was observed in the controlled scan, but this implementation boundary should remain part of precision-systematics studies.

## Conditional and unconditional observables

At low charge, the event can fail to produce an accepted active-volume deposit. Always distinguish:

- mean deposition over **all** generated events;
- conditional `dE/dx` among events with primary activity;
- active-LAr hit probability;
- packet-production probability;
- reconstruction probability.

A clean `q²` trend among surviving events does not imply a high total detection efficiency.

## Interpreting the `q=0.3e` realistic sample

The first realistic run deliberately used `q=0.3e` as a high-signal integration test. Its mean primary active-LAr deposition was about `19.08 MeV` over about `1.086m`, with mean `dE/dx≈0.01758 MeV/mm`.

A naive `q²` rescaling from `0.3e` to `0.01e` is a factor of 900 reduction. The corresponding low-charge sample will therefore be dominated by threshold, zero-hit, and reconstruction-efficiency questions and requires substantially more events.
