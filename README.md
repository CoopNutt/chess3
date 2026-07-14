# Chess 3

Multiplayer battle chess for 2 to 6 players. Pick a map, build your army,
send your friends a lobby code and fight until one king is left standing.

Download the latest Chess3.exe from the releases page. No install, just run it.

## How to play

Host a game and you get two codes. The wifi code works for anyone on your
network, the internet code works anywhere if the auto port forward succeeded
(the lobby tells you). Friends open the game, hit join and type the code.
People running the game on your network show up as online and you can invite
them directly, they get a popup with an accept button.

Match settings are picked by the host in the lobby:

- Map: hexagon, octagon, square or triangle
- Move timer and total game clock
- Troop swaps, put Catapults, Valkyries, Golems, Juggernauts, Snipers or
  Wardens in your army in place of the default troops

## Rules

No checkmate, you have to actually capture the king. You also cannot make a
move that would leave your own king open to capture, same as regular chess.
Lose your king and your whole army is gone, but you get one last act of
revenge: curse any empty tile into a graveyard that nothing can enter except
skeletons.

Pawns move 1 forward (2 on their first move), capture on the three forward
diagonals and become queens on the far side of the board. Press H in game to
see how every troop moves, each one has a picture.

Some troop highlights:

| Troop | What it does |
|---|---|
| Cannon | Kills by leaping over exactly one piece |
| Archer | Shoots enemies 2 tiles away without moving |
| Wizard | Teleports within 2 tiles, strikes like lightning |
| Dragon | Flies up to 3 tiles, breathes fire when it lands on someone |
| Bomber | Explodes when it captures or dies. Also explodes by itself after 10 moves |
| Ghost | Slides through other pieces |
| Necromancer | Raises skeletons from your dead pawns, they crumble after 3 moves |
| Juggernaut | Charges up to 5 tiles and hits the first thing in its path |
| Warden | Pieces next to it cannot be captured by normal moves |
| Golem | Immune to arrows, boulders and explosions |
| Thief | Never fights, swaps places with any nearby piece instead. In every starting army |
| Shaman | Collects a soul per kill, spend them to morph into other troops |
| Mimic | Moves like whatever piece was moved last in the game. In every starting army |

Heavy hits crack the tiles permanently. Right click draws planning arrows
like chess.com. Select any piece to see its moves, what it can take and what
it protects.

## Building from source

Python 3.12+ with pygame-ce and numpy, then:

```
build.bat
```

Tests: `python -m unittest discover -s tests`

The game updates itself, when a new release is out it asks before restarting.
