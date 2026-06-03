import Semantics.FixedPoint
import Semantics.BraidStrand
import Semantics.BraidBracket
import Semantics.MeshRouting

/-!
# BraidVCNBridge — Map braid operations to VCN frame encoding.

Bridges the braid algebra (BraidStrand, BraidBracket) to the VCN video encode
substrate for GPU-accelerated computation.

## Byte Layout (matches Python `vcn_compute_substrate._serialize_strand`)

All integers are little-endian. Q16_16 values are serialized as unsigned 32-bit
via two's-complement bit pattern (matching `Q16_16.toBits`).

### BraidBracket: 21 bytes
```
[lower:4][upper:4][gap:4][kappa:4][phi:4][admissible:1]
```

### BraidStrand: 42 bytes
```
[phaseAcc.x:4][phaseAcc.y:4][parity:1][slot:4]
[residue:4][jitter:4][bracket:21]
```
-/

namespace Semantics.BraidVCNBridge

open Semantics
open Semantics.BraidBracket
open Semantics.BraidBracket.BraidBracket
open Semantics.BraidStrand

/-- Pack a Q16_16 value to 4 bytes (little-endian, unsigned bit pattern).
    Matches Python `_q16_to_bytes` and `Q16_16.toBits`. -/
private def packQ16 (v : Q16_16) : Array UInt8 :=
  let n := v.val.toNat
  #[ UInt8.ofNat (n % 256),
     UInt8.ofNat ((n / 256) % 256),
     UInt8.ofNat ((n / 65536) % 256),
     UInt8.ofNat ((n / 16777216) % 256) ]

/-- Pack a UInt32 to 4 bytes (little-endian). -/
private def packU32 (v : UInt32) : Array UInt8 :=
  let n := v.toNat
  #[ UInt8.ofNat (n % 256),
     UInt8.ofNat ((n / 256) % 256),
     UInt8.ofNat ((n / 65536) % 256),
     UInt8.ofNat ((n / 16777216) % 256) ]

/-- Pack a Bool to 1 byte. -/
private def packBool (v : Bool) : Array UInt8 :=
  if v then #[1] else #[0]

/-- Encode a BraidBracket to 21 bytes.

  Layout: [lower:4][upper:4][gap:4][kappa:4][phi:4][admissible:1]
  Matches Python `_serialize_bracket`.
-/
def encodeBraidBracket (b : BraidBracket) : Array UInt8 :=
  packQ16 b.lower ++ packQ16 b.upper ++ packQ16 b.gap ++
  packQ16 b.kappa ++ packQ16 b.phi ++ packBool b.admissible

/-- Encode a BraidStrand to 42 bytes.

  Layout: [phaseAcc.x:4][phaseAcc.y:4][parity:1][slot:4]
          [residue:4][jitter:4][bracket:21]
  Matches Python `_serialize_strand`.
-/
def encodeBraidStrand (s : BraidStrand) : Array UInt8 :=
  packQ16 s.phaseAcc.x ++
  packQ16 s.phaseAcc.y ++
  packBool s.parity ++
  packU32 s.slot ++
  packQ16 s.residue ++
  packQ16 s.jitter ++
  encodeBraidBracket s.bracket

def encodeBraidCrossing (bij bi bj : BraidBracket) : Array UInt8 :=
  let res := crossingResidual bij bi bj
  packQ16 res.lower ++ packQ16 res.upper ++
  packQ16 res.gap ++ packQ16 res.kappa ++ packQ16 res.phi

-- TODO(lean-port): Mountain merge encoding (needs BraidField import)
-- TODO(lean-port): PISTField frame encoding (needs BraidField import)
-- TODO(lean-port): eigensolid_convergence — crossing loop stabilizes
-- TODO(lean-port): receipt_invertible — encode + decode is bijective

end Semantics.BraidVCNBridge
