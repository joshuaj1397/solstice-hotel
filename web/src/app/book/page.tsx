import type { Metadata } from "next";
import { Suspense } from "react";
import { BookStay } from "@/components/book/BookStay";
import { Spinner } from "@/components/ui";

export const metadata: Metadata = { title: "Book a stay" };

export default function BookPage() {
  return (
    <Suspense fallback={<div className="p-10"><Spinner label="Loading" /></div>}>
      <BookStay />
    </Suspense>
  );
}
