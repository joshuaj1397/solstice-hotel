import type { Metadata } from "next";
import { GroupRequest } from "@/components/groups/GroupRequest";

export const metadata: Metadata = { title: "Groups & events" };

export default function GroupsPage() {
  return (
    <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6">
      <p className="eyebrow">Groups &amp; events</p>
      <h1 className="text-4xl font-semibold">A priced proposal in a minute, not two days</h1>
      <p className="mb-6 mt-2 max-w-3xl text-muted">
        Our booking agent checks live availability, blackout dates, meeting space and Solstice&apos;s group pricing rules. Anything inside the rules is held for you straight away. Anything outside goes to our sales team, along with options we can confirm today.
      </p>
      <GroupRequest />
    </div>
  );
}
