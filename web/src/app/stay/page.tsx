import type { Metadata } from "next";
import { StayCompanion } from "@/components/stay/StayCompanion";

export const metadata: Metadata = { title: "My stay" };

export default function StayPage() {
  return <StayCompanion />;
}
