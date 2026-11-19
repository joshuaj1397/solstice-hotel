import { relay } from "@/lib/server/agent";
import { connection } from "next/server";

export async function GET() {
  await connection(); // always fetched at request time (inventory and rates are live)
  return relay("/v1/properties");
}
