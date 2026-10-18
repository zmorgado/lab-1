type StepHeadingProps = { id: string; step: number; children: string }

export default function StepHeading({ id, step, children }: StepHeadingProps) {
  return (
    <header className="mb-4">
      <p className="font-mono text-[11px] tracking-[0.06em] text-pencil uppercase">Step {step}</p>
      <h2 id={id} className="mt-1 text-2xl font-semibold tracking-[-0.015em]">
        {children}
      </h2>
    </header>
  )
}
