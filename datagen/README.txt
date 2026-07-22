aws s3 ls --profile ac-cct-crt


  What's live                                                                                                                                                                                                 
                                                                     
  ┌───────────────────────┬────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐                                                  
  │       Resource        │                                                           Identifier                                                           │                                                  
  ├───────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤                                                  
  │ Cloudflare tunnel     │ arc75-qa-agent (id 5cca63d6-be91-4636-b270-ed67cfa7a853) — healthy, 4 connections (YUL + EWR)                                  │                                                  
  ├───────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤                                                  
  │ Private network route │ 10.111.196.0/22 → arc75-qa-agent tunnel                                                                                        │                                                  
  ├───────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤                                                  
  │ WARP Split Tunnel     │ 10.0.0.0/8 replaced with 14 narrower prefixes excluding 10.111.196.0/22 (other 10.x private LANs still bypass WARP)            │                                                  
  ├───────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤                                                  
  │ ECS service           │ arc75-qa-agent-cloudflared on cluster arc75-qa-agent, 1/1 running, rev 3                                                       │
  ├───────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Task definition       │ arc75-qa-agent-cloudflared:3 — cloudflare/cloudflared:latest, TUNNEL_TRANSPORT_PROTOCOL=http2, sysctl net.ipv4.ping_group_range │
  ├───────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤                                                  
  │ Secret                │ arc75/cloudflared/tunnel-token in Secrets Manager                                                                              │
  ├───────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤                                                  
  │ Log group             │ /ecs/arc75-qa-agent (14d retention)                                                                                            │
  ├───────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤                                                  
  │ Security group        │ sg-0d8fdad116f178dbe (default egress, no ingress)                                                                              │
  ├───────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤                                                  
  │ IAM                   │ Reused existing ac-cct-crt-ecs-task-execution-role — org SCP blocks iam:CreateRole                                             │
  └───────────────────────┴────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘                                                  
                                                                  
  Notes on choices I made                                                                                                                                                                                     
                                                                  
  - HTTP/2 transport rather than default QUIC — AC's TGW-central egress blocks UDP to *.argotunnel.com:7844. Logs showed QUIC retries timing out; HTTP/2 over TCP registered in <2s.                          
  - No new IAM roles — SCP p-w8p5eioi denies iam:CreateRole. Reused ac-cct-crt-ecs-task-execution-role which already has AmazonECSTaskExecutionRolePolicy + SecretsManagerReadWrite. This role is shared with
  other CCT services; keep that in mind if you add more secrets.                                                                                                                                              
  - WARP exclude change is account-global — affects every device enrolled in the arc75 team, not just your Mac. The narrower prefixes preserve the original "don't tunnel local LAN" intent for all 10.x space
   except the one VPC.                                                                                                                                                                                        
  - Left the stray 10.0.1.0/24 tunnel route in place — it's harmless but doesn't belong to this VPC. Delete if you want.
  - ICMP (ping) to private IPs does not work through this setup. TCP works end-to-end. cloudflared's ICMP proxy is enabled in rev 3 via net.ipv4.ping_group_range, but Cloudflare's edge still returns "Destination Host Unreachable" for ICMP to 10.111.196.0/22 — this needs Gateway proxy + likely MASQUE tunnel protocol to fix, not worth pursuing. Use nc/curl/ssh for reachability checks.
                                                                                                                                                                                                              
  What you do on your Mac

  brew install --cask cloudflare-warp
  open -a "Cloudflare WARP"

  # Prereq on the Zero Trust tenant (admin, one-time): at least one login method must be
  # enabled for "WARP authentication identity" AND a device enrollment Allow rule matching
  # your email must exist. One-time PIN is the fastest login method to stand up.
  # Settings → Authentication → Login methods       (enable method for WARP auth identity)
  # Settings → WARP Client → Device enrollment permissions → Policies  (add Allow rule)

  # Enroll the device. The GUI button ("Login with Cloudflare Zero Trust") is the supported
  # path; the warp-cli equivalent is:
  /Applications/Cloudflare\ WARP.app/Contents/Resources/warp-cli registration new arc75
  # Complete the IdP flow in the browser that opens. Then:
  /Applications/Cloudflare\ WARP.app/Contents/Resources/warp-cli status   # should show Connected

  Smoke test

  # Use TCP — ICMP is not forwarded through this setup (see notes above).
  nc -vz -w 5 10.111.198.144 22   # kafka-client EC2, private IP, expect "succeeded!"
  # Or: aws --profile ac-cct-crt --region ca-central-1 ssm start-session --target i-04ee64277a4a29f69

  If nc succeeds, every TCP service in 10.111.196.0/22 (RDS, ALB, EC2) is reachable from
  your Mac by private IP as long as security groups permit.                      