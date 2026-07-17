# core/registry — per-cell descriptors (declare once, swap freely)

The generic engine (catalog, seed, runner, …) is written **once**. Everything that differs between a
feed, a product, or an environment lives in **one small declarative file** here. A run picks one from
each folder: `product × env × feed`.

```
registry/
├── feeds/       one file per business domain  (fd, soc, nc, anc, baggage, seatchange, bookingchange, nonmvp)
├── products/    one file per chatbot deployment (bravo, alpha, …)
└── envs/        one file per environment        (crt, int, bat)
```

- **feed** file = gap-doc path + persona template + judge/verdict schema + checkpoint auditor + column field-map.
- **product** file = display name + transcript dialect + optional persona/judge overrides.
- **env** file = endpoint + OTP strategy + AWS profile/account + seed targets (Kafka/Aurora/S3/DDS). No secrets — names of secrets only.

**Adding a new feed / product / env = adding one file here. No engine code changes.**
Format is YAML (illustrative stubs below); the loader lives in `core/`. These are the "generic file
for each feed" from the requirements — see [`../../README.md`](../../README.md).
