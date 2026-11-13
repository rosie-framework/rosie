# Security

Use secure mode on any network you do not control. Open mode is still there for a laptop and a sim on localhost.

| Mode | Who can use the bus | What `fleet list` shows |
|---|---|---|
| Open | Anyone who can reach the router | Every presence publisher |
| Secure (`--secure`) | Peers that know the fleet secret (Zenoh usrpwd) | Enrolled robot ids only |

```bash
# laptop
rosie fleet init --fleet lab --secure
rosie fleet add --fleet lab --robot bot1 --profile rosmaster_x3
rosie router --fleet lab --secure

# robot
rosie fleet secret --fleet lab --set
rosie robot setup --fleet lab --robot bot1 --profile rosmaster_x3 --secure --connect tcp/192.168.1.10:7447

# laptop
rosie fleet list --fleet lab --secure
```

The secret is a file under `~/.rosie` on each machine. It is not sent on the bus; copy it to the robot yourself with `fleet secret --set`. `rosie secret apply --config rosie-bridge.json5 --fleet lab` writes the user and password hash into a bridge config that was created without `--secure`.

Holding the secret still lets a peer publish as any robot id. The allowlist filters what the laptop tools display; it is not a per-key ACL. Treat the secret like a password for the whole fleet.

Network isolation still matters. Put the robots and the router on a network that strangers are not on. See [Networking](networking.md) and [Management](management.md).
