# Authentication in new profiles

Verify authentication in the exact consumer profile before reporting it ready. A working sibling or a key in the server environment does not prove access: the observed Kimi error explicitly said the named profile reads keys only from its own `.env`.

Verified Kimi Code identifiers: provider `kimi-coding`, model `kimi-for-coding`. Its authentication error names `KIMI_API_KEY` and `KIMI_CODING_API_KEY`. Inspect credential names and nonempty status without printing values. A working sibling may also have `KIMI_BASE_URL`; account for its connection settings deliberately.

A separate profile does not inherently require a distinct provider key. Reusing an existing credential requires authorization; do not copy credentials merely because profile creation was requested. Keep them local and outside Git. Once permission is given, apply the scoped fix rather than repeatedly requesting it.

Run a bounded harmless request in the target profile's fresh runtime after setup. Distinguish model configuration, authentication, skill discovery, and actual tool execution. A successful test with the previous provider does not verify a newly selected provider. The CLI can exit zero while reporting an authentication failure, so inspect output rather than relying on exit status.
