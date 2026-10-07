export function Composer({
  value,
  onChange,
  onSubmit,
  onStop,
  streaming,
}: {
  value: string
  onChange: (value: string) => void
  onSubmit: () => void
  onStop: () => void
  streaming: boolean
}) {
  return (
    <form
      className="border-t border-line bg-paper px-3 py-3"
      onSubmit={(event) => {
        event.preventDefault()
        onSubmit()
      }}
    >
      <div className="mx-auto flex w-full max-w-3xl items-end gap-2">
        <label className="sr-only" htmlFor="question">
          Question
        </label>
        <textarea
          id="question"
          value={value}
          rows={2}
          placeholder="Ask about a paper, note, or file"
          className="max-h-40 min-h-12 flex-1 resize-none rounded-2xl border border-line bg-paper-raised px-4 py-3 text-base outline-none focus:border-accent"
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault()
              onSubmit()
            }
          }}
        />
        {streaming ? (
          <button type="button" className="rounded-full border border-line px-4 py-3 text-sm" onClick={onStop}>
            Stop
          </button>
        ) : (
          <button type="submit" className="rounded-full bg-accent px-4 py-3 text-sm font-medium text-white">
            Send
          </button>
        )}
      </div>
    </form>
  )
}
