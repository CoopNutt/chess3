# Chess 3 art guide

How to make custom piece art for the game.

## The short version

- **24 PNG files**, one per piece, named exactly like the list below
- **256 x 256 pixels**, square, **transparent background** (PNG with alpha)
- Draw the piece **in white / light gray with a dark outline** — the game
  draws the colored circle underneath for you, so every player's color works
  automatically. Do NOT bake in a background circle or any player color
- Keep about **25 px of empty margin** on every side so nothing gets clipped
- Put the files in a folder called `assets\pieces\` next to `Chess3.exe`,
  restart the game, done. Any piece without a file keeps the built-in look,
  so you can deliver art piece by piece

## The files

| File | Piece | What it is (for drawing inspiration) |
|---|---|---|
| `K.png` | King | The boss. Classic crown |
| `Q.png` | Queen | Big crown, strongest piece |
| `R.png` | Rook | Castle tower |
| `B.png` | Bishop | The pointy hat |
| `N.png` | Knight | Horse head |
| `P.png` | Pawn | The little guy |
| `CN.png` | Cannon | Old-school cannon barrel on a wheel |
| `AR.png` | Archer | Bow and arrow |
| `WZ.png` | Wizard | Pointed hat, stars, teleports |
| `DR.png` | Dragon | Wings and fire |
| `CH.png` | Champion | Armored shield bruiser |
| `BM.png` | Bomber | Round bomb with a lit fuse |
| `GH.png` | Ghost | Classic wavy-bottom ghost |
| `NE.png` | Necromancer | Skull guy, raises the dead |
| `SK.png` | Skeleton | The raised dead. Bony pawn |
| `CT.png` | Catapult | Siege engine that lobs boulders |
| `VA.png` | Valkyrie | Winged helmet warrior |
| `GO.png` | Golem | Big stone body, cracked rock |
| `JG.png` | Juggernaut | Charging bull / battering ram |
| `SN.png` | Sniper | Crossbow with a scope |
| `WD.png` | Warden | Tower shield protector |
| `TF.png` | Thief | Masked, swaps pieces around |
| `SH.png` | Shaman | Tribal mask, collects souls |
| `MI.png` | Mimic | Treasure chest with teeth |

## Style rules (so the set looks like one game)

1. **Readable at 32 px.** Squint test: shrink your art way down — if you
   can't instantly tell which piece it is, simplify. Strong silhouette beats
   fine detail
2. **Consistent line weight** across all 24. If your outlines are ~8 px
   thick at 256 x 256 on one piece, keep that for all of them
3. **Same lighting/angle** for the whole set (front-facing, flat shading is
   the safe pick)
4. **Similar visual weight** — no piece should look twice as big as another
   inside its canvas. Fill roughly the same area
5. Light-on-dark: the art sits on a colored disc that can be any of white,
   black, red, blue, gold or purple, so white shapes with a **dark outline**
   read on all of them

## Optional extras (same format, same folder)

| File | What | Size |
|---|---|---|
| `tombstone.png` | The graveyard-curse tile marker | 256 x 256 |
| `logo.png` | Menu logo (replaces the dragon-in-a-hexagon) | 512 x 512 |

## Delivering

Drop the folder in the repo (`assets/pieces/`) or just send the PNGs.
Whoever runs the game puts them next to `Chess3.exe` in `assets\pieces\`.
Restart the game after swapping files — art loads once at startup.
