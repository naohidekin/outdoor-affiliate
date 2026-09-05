import type { MedicalAdviceData } from "@/lib/medicalAdviceData";

type MedicalAdviceProps = MedicalAdviceData;

export default function MedicalAdvice({ title, body, bullets }: MedicalAdviceProps) {
  return (
    <aside
      aria-label="医師からのアドバイス"
      className="rounded-lg border-l-4 border-emerald-500 bg-emerald-50 p-5 my-8 not-prose"
    >
      <h3 className="flex items-center gap-2 font-bold text-emerald-900 text-base mb-3">
        🩺 医師から一言：{title}
      </h3>
      <p className="text-gray-800 leading-loose text-base">{body}</p>
      {bullets.length > 0 && (
        <ul className="list-disc pl-5 mt-3 space-y-3 text-gray-800 text-base leading-relaxed">
          {bullets.map((b, i) => (
            <li key={i}>{b}</li>
          ))}
        </ul>
      )}
      <p className="mt-4 text-xs text-gray-500 leading-relaxed">
        ※本記述は一般的な医学情報の提供であり、個別の診療行為ではありません。症状がある場合は医療機関を受診してください。
      </p>
    </aside>
  );
}
