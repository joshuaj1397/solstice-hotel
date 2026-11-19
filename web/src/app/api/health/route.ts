import { connection } from "next/server";
import { relay } from "@/lib/server/agent";

export async function GET() {
  await connection();
  return relay("/health");
}
