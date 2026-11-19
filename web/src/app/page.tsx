import Link from "next/link";
import { SignInForm } from "@/components/SignInForm";
import { QuickSearch } from "@/components/book/QuickSearch";

export default function Home() {
  return (
    <div className="relative overflow-hidden">
      <div
        aria-hidden
        className="pointer-events-none absolute -top-40 left-1/2 size-[46rem] -translate-x-1/2 rounded-full bg-[radial-gradient(circle,var(--color-sun-soft),transparent_65%)]"
      />
      <section className="relative mx-auto max-w-7xl px-4 pb-10 pt-14 sm:px-6">
        <p className="eyebrow">Solstice Hotel Group · 140 hotels</p>
        <h1 className="mt-3 max-w-3xl text-5xl font-semibold leading-[1.05] sm:text-6xl">
          Your stay, handled. <span className="text-sun">Day or night.</span>
        </h1>
        <p className="mt-4 max-w-2xl text-lg text-muted">
          Meet Sol, the Solstice concierge. Late check-out, loyalty perks, policies, a new booking, or a problem that needs a person: Sol either sorts it out or gets the right team member on it with the whole story attached.
        </p>
      </section>

      <section className="relative mx-auto grid max-w-7xl gap-6 px-4 pb-16 sm:px-6 lg:grid-cols-3">
        <div className="card p-6">
          <p className="eyebrow">Already booked?</p>
          <h2 className="mb-4 mt-1 text-2xl font-semibold">Manage my stay</h2>
          <SignInForm />
        </div>
        <div className="card p-6">
          <p className="eyebrow">Plan a trip</p>
          <h2 className="mb-4 mt-1 text-2xl font-semibold">Book a stay</h2>
          <QuickSearch />
        </div>
        <div className="card flex flex-col p-6">
          <p className="eyebrow">Weddings · teams · conferences</p>
          <h2 className="mt-1 text-2xl font-semibold">Group &amp; event blocks</h2>
          <p className="mt-3 flex-1 text-muted">
            Tell us about your group and get a priced proposal in about a minute instead of two days. In-policy requests are held for you on the spot.
          </p>
          <Link href="/groups" className="btn btn-dusk mt-5 self-start">Request a group proposal</Link>
        </div>
      </section>
    </div>
  );
}
