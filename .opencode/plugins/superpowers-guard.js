export default async function SuperpowersDfrGuard() {
  process.env.SUPERPOWERS_DISABLE_TELEMETRY = "1";
  process.env.CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC = "1";
  return {};
}
