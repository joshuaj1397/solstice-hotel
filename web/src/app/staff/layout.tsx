import type { Metadata } from "next";
import { Suspense } from "react";
import { StaffGate } from "@/components/staff/StaffGate";
import { Spinner } from "@/components/ui";

export const metadata: Metadata = { title: "Staff console" };

export default function StaffLayout({ children }: LayoutProps<"/staff">) {
  return (
    <Suspense fallback={<div className="p-10"><Spinner label="Loading staff console" /></div>}>
      <StaffGate>{children}</StaffGate>
    </Suspense>
  );
}
