type IconProps = { className?: string; size?: number };

export function IconFolder({ className, size = 16 }: IconProps) {
  return (
    <svg className={className} width={size} height={size} viewBox="0 0 16 16" fill="currentColor" aria-hidden>
      <path d="M1.75 1A1.75 1.75 0 0 0 0 2.75v10.5C0 14.216.784 15 1.75 15h12.5A1.75 1.75 0 0 0 16 13.25v-8.5A1.75 1.75 0 0 0 14.25 3H7.5a.25.25 0 0 1-.2-.1l-.9-1.2C6.07 1.26 5.55 1 5 1H1.75Z" />
    </svg>
  );
}

export function IconFile({ className, size = 16 }: IconProps) {
  return (
    <svg className={className} width={size} height={size} viewBox="0 0 16 16" fill="currentColor" aria-hidden>
      <path d="M2 1.75C2 .784 2.784 0 3.75 0h6.586c.464 0 .909.184 1.237.513l2.914 2.914c.329.328.513.773.513 1.237v9.586A1.75 1.75 0 0 1 13 16H3.75A1.75 1.75 0 0 1 2 14.25V1.75Zm1.75-.25a.25.25 0 0 0-.25.25v12.5c0 .138.112.25.25.25h9.25a.25.25 0 0 0 .25-.25V6h-2.75A1.75 1.75 0 0 1 9 4.25V1.5H3.75Zm6.75.062V4.25c0 .138.112.25.25.25h2.688a.25.25 0 0 0 .177-.073L11.5 2.427a.25.25 0 0 0-.073-.177Z" />
    </svg>
  );
}

export function IconUpload({ className, size = 16 }: IconProps) {
  return (
    <svg className={className} width={size} height={size} viewBox="0 0 16 16" fill="currentColor" aria-hidden>
      <path d="M2.75 14A1.75 1.75 0 0 1 1 12.25v-2.5a.75.75 0 0 1 1.5 0v2.5c0 .138.112.25.25.25h10.5a.25.25 0 0 0 .25-.25v-2.5a.75.75 0 0 1 1.5 0v2.5A1.75 1.75 0 0 1 13.25 14H2.75Z" />
      <path d="M7.25 8.689a.75.75 0 0 1 1.5 0v4.396l1.995-2.096a.75.75 0 0 1 1.088 1.034l-3.5 3.675a.75.75 0 0 1-1.088 0l-3.5-3.675a.75.75 0 1 1 1.088-1.034l1.995 2.096V8.69Z" />
      <path d="M8 0a4 4 0 0 0-4 4v2.25a.75.75 0 0 0 1.5 0V4a2.5 2.5 0 1 1 5 0v2.25a.75.75 0 0 0 1.5 0V4a4 4 0 0 0-4-4Z" />
    </svg>
  );
}

export function IconHome({ className, size = 16 }: IconProps) {
  return (
    <svg className={className} width={size} height={size} viewBox="0 0 16 16" fill="currentColor" aria-hidden>
      <path d="M6.906.664a1.749 1.749 0 0 1 2.187 0l5.25 4.2c.415.332.657.835.657 1.367v7.019A1.75 1.75 0 0 1 13.25 15h-3.5a.75.75 0 0 1-.75-.75V9H7v5.25a.75.75 0 0 1-.75.75h-3.5A1.75 1.75 0 0 1 1 13.25V6.23c0-.531.242-1.035.657-1.367l5.25-4.2Z" />
    </svg>
  );
}

export function IconBrowse({ className, size = 16 }: IconProps) {
  return (
    <svg className={className} width={size} height={size} viewBox="0 0 16 16" fill="currentColor" aria-hidden>
      <path d="M1.75 2A1.75 1.75 0 0 0 0 3.75v8.5C0 13.216.784 14 1.75 14h12.5A1.75 1.75 0 0 0 16 12.25v-8.5A1.75 1.75 0 0 0 14.25 2H1.75ZM1.5 3.75a.25.25 0 0 1 .25-.25h12.5a.25.25 0 0 1 .25.25v8.5a.25.25 0 0 1-.25.25H1.75a.25.25 0 0 1-.25-.25v-8.5Z" />
      <path d="M3 5.75a.75.75 0 0 1 .75-.75h8.5a.75.75 0 0 1 0 1.5h-8.5A.75.75 0 0 1 3 5.75Zm0 2.5a.75.75 0 0 1 .75-.75h8.5a.75.75 0 0 1 0 1.5h-8.5a.75.75 0 0 1-.75-.75Zm0 2.5a.75.75 0 0 1 .75-.75h5.5a.75.75 0 0 1 0 1.5h-5.5a.75.75 0 0 1-.75-.75Z" />
    </svg>
  );
}

export function IconChevronRight({ className, size = 12 }: IconProps) {
  return (
    <svg className={className} width={size} height={size} viewBox="0 0 16 16" fill="currentColor" aria-hidden>
      <path d="M6.22 3.22a.75.75 0 0 1 1.06 0l4.25 4.25a.75.75 0 0 1 0 1.06l-4.25 4.25a.751.751 0 0 1-1.042-.018.751.751 0 0 1-.018-1.042L9.94 8 6.22 4.28a.75.75 0 0 1 0-1.06Z" />
    </svg>
  );
}

export function IconIngestion({ className, size = 20 }: IconProps) {
  return (
    <svg className={className} width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden>
      <rect x="3" y="3" width="18" height="18" rx="4" stroke="currentColor" strokeWidth="2" />
      <path d="M8 12h8M12 8v8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

export function IconPipeline({ className, size = 16 }: IconProps) {
  return (
    <svg className={className} width={size} height={size} viewBox="0 0 16 16" fill="currentColor" aria-hidden>
      <path d="M0 3.75C0 2.784.784 2 1.75 2h12.5c.966 0 1.75.784 1.75 1.75v8.5A1.75 1.75 0 0 1 14.25 14H1.75A1.75 1.75 0 0 1 0 12.25v-8.5ZM1.75 3a.25.25 0 0 0-.25.25v8.5c0 .138.112.25.25.25h12.5a.25.25 0 0 0 .25-.25v-8.5a.25.25 0 0 0-.25-.25H1.75Z" />
      <path d="M3.5 5.75a.75.75 0 0 1 .75-.75h2.5a.75.75 0 0 1 0 1.5h-2.5a.75.75 0 0 1-.75-.75Zm0 3a.75.75 0 0 1 .75-.75h6.5a.75.75 0 0 1 0 1.5h-6.5a.75.75 0 0 1-.75-.75Zm0 3a.75.75 0 0 1 .75-.75h4a.75.75 0 0 1 0 1.5h-4a.75.75 0 0 1-.75-.75Z" />
    </svg>
  );
}

export function IconTracking({ className, size = 16 }: IconProps) {
  return (
    <svg className={className} width={size} height={size} viewBox="0 0 16 16" fill="currentColor" aria-hidden>
      <path d="M1.5 1.75a.75.75 0 0 0-1.5 0v12.5c0 .414.336.75.75.75H14.25a.75.75 0 0 0 0-1.5H1.5V1.75Z" />
      <path d="M13.97 3.97a.75.75 0 0 1 1.06 1.06l-4.5 4.5a.75.75 0 0 1-1.06 0L7.75 7.81 4.28 11.28a.75.75 0 0 1-1.06-1.06l4-4a.75.75 0 0 1 1.06 0l1.72 1.72 3.97-3.97Z" />
    </svg>
  );
}

export function IconChat({ className, size = 16 }: IconProps) {
  return (
    <svg className={className} width={size} height={size} viewBox="0 0 16 16" fill="currentColor" aria-hidden>
      <path d="M1.75 2h12.5c.966 0 1.75.784 1.75 1.75v7.5A1.75 1.75 0 0 1 14.25 13H5.061l-3.57 3.57A.75.75 0 0 1 .25 16v-1.75v-10.5C.25 2.784 1.034 2 1.75 2ZM1.75 3.5a.25.25 0 0 0-.25.25v7.5c0 .138.112.25.25.25h12.5a.25.25 0 0 0 .25-.25v-7.5a.25.25 0 0 0-.25-.25H1.75Z" />
    </svg>
  );
}

export function IconEvaluation({ className, size = 16 }: IconProps) {
  return (
    <svg className={className} width={size} height={size} viewBox="0 0 16 16" fill="currentColor" aria-hidden>
      <path d="M1.5 1.75V13.5h13.75a.75.75 0 0 1 0 1.5H.75a.75.75 0 0 1-.75-.75V1.75a.75.75 0 0 1 1.5 0Zm14.28 2.53-5.25 5.25a.75.75 0 0 1-1.06 0L7 7.06 4.28 9.78a.75.75 0 0 1-1.06-1.06l3.25-3.25a.75.75 0 0 1 1.06 0L10 7.94l4.72-4.72a.75.75 0 0 1 1.06 1.06Z" />
    </svg>
  );
}

export function IconPrompts({ className, size = 16 }: IconProps) {
  return (
    <svg className={className} width={size} height={size} viewBox="0 0 16 16" fill="currentColor" aria-hidden>
      <path d="M0 2.75C0 1.784.784 1 1.75 1h12.5c.966 0 1.75.784 1.75 1.75v10.5A1.75 1.75 0 0 1 14.25 15H1.75A1.75 1.75 0 0 1 0 13.25Zm1.75-.25a.25.25 0 0 0-.25.25v10.5c0 .138.112.25.25.25h12.5a.25.25 0 0 0 .25-.25V2.75a.25.25 0 0 0-.25-.25ZM3.5 4.75a.75.75 0 0 1 .75-.75h7.5a.75.75 0 0 1 0 1.5h-7.5a.75.75 0 0 1-.75-.75Zm0 3a.75.75 0 0 1 .75-.75h7.5a.75.75 0 0 1 0 1.5h-7.5a.75.75 0 0 1-.75-.75Zm0 3a.75.75 0 0 1 .75-.75h4.5a.75.75 0 0 1 0 1.5h-4.5a.75.75 0 0 1-.75-.75Z" />
    </svg>
  );
}

export function IconGuardrails({ className, size = 16 }: IconProps) {
  return (
    <svg className={className} width={size} height={size} viewBox="0 0 16 16" fill="currentColor" aria-hidden>
      <path d="M8 0L1 3v5c0 4.42 3 7.5 7 8 4-.5 7-3.58 7-8V3L8 0Zm0 1.5l5.5 2.35V8c0 3.53-2.37 5.97-5.5 6.46C4.87 13.97 2.5 11.53 2.5 8V3.85L8 1.5Zm-.72 4.22a.75.75 0 0 1 1.06 0L10 7.38l1.66-1.66a.75.75 0 1 1 1.06 1.06l-2.19 2.19a.75.75 0 0 1-1.06 0L8 7.5l-.66.66a.75.75 0 0 1-1.06-1.06l.94-.94Z" />
    </svg>
  );
}

export function IconMoreHorizontal({ className, size = 16 }: IconProps) {
  return (
    <svg className={className} width={size} height={size} viewBox="0 0 16 16" fill="currentColor" aria-hidden>
      <path d="M2.75 8a1.25 1.25 0 1 1 2.5 0 1.25 1.25 0 0 1-2.5 0Zm4 0a1.25 1.25 0 1 1 2.5 0 1.25 1.25 0 0 1-2.5 0Zm4 0a1.25 1.25 0 1 1 2.5 0 1.25 1.25 0 0 1-2.5 0Z" />
    </svg>
  );
}
export function IconSources({ className, size = 16 }: IconProps) {
  return (
    <svg className={className} width={size} height={size} viewBox="0 0 16 16" fill="currentColor" aria-hidden>
      <path d="M4.5 1.75a.75.75 0 0 0-1.5 0v12.5a.75.75 0 0 0 1.5 0V1.75ZM8.5 1.75a.75.75 0 0 0-1.5 0v12.5a.75.75 0 0 0 1.5 0V1.75ZM12.5 1.75a.75.75 0 0 0-1.5 0v12.5a.75.75 0 0 0 1.5 0V1.75Z" />
    </svg>
  );
}
export function IconArrowRight({ className, size = 16 }: IconProps) {
  return (
    <svg className={className} width={size} height={size} viewBox="0 0 16 16" fill="currentColor" aria-hidden>
      <path fillRule="evenodd" d="M4.75 3.75a.75.75 0 0 1 .75.75v6.537L9.191 8.708a.75.75 0 0 1 1.06 1.06l-4.5 4.5a.75.75 0 0 1-1.06 0l-4.5-4.5a.75.75 0 1 1 1.06-1.06L7.75 11.087V4.5a.75.75 0 0 1 .75-.75Z" clipRule="evenodd" />
    </svg>
  );
}
export function IconBucket({ className, size = 16 }: IconProps) { return (<svg className={className} width={size} height={size} viewBox="0 0 16 16" fill="currentColor" aria-hidden><path d="M14 6H2l1 9h10l1-9zM4 3h8v2H4z" /></svg>); }
export function IconCheck({ className, size = 16 }: IconProps) { return (<svg className={className} width={size} height={size} viewBox="0 0 16 16" fill="currentColor" aria-hidden><path d="M6 12L2 8l1.5-1.5L6 9l6-6L13.5 4.5z" /></svg>); }
export function IconCheckCircle({ className, size = 16 }: IconProps) { return (<svg className={className} width={size} height={size} viewBox="0 0 16 16" fill="currentColor" aria-hidden><path d="M8 0a8 8 0 1 0 0 16A8 8 0 0 0 8 0zm3.5 4.5l-5 5-2-2L3 8.5l3.5 3.5 6-6L11.5 4.5z" /></svg>); }
export function IconCopy({ className, size = 16 }: IconProps) { return (<svg className={className} width={size} height={size} viewBox="0 0 16 16" fill="currentColor" aria-hidden><path d="M4 1h9v12H4V1zM2 3h1v12h10v1H2V3z" /></svg>); }
export function IconGrid({ className, size = 16 }: IconProps) { return (<svg className={className} width={size} height={size} viewBox="0 0 16 16" fill="currentColor" aria-hidden><path d="M0 0h7v7H0V0zm9 0h7v7H9V0zM0 9h7v7H0V9zm9 0h7v7H9V9z" /></svg>); }
export function IconList({ className, size = 16 }: IconProps) { return (<svg className={className} width={size} height={size} viewBox="0 0 16 16" fill="currentColor" aria-hidden><path d="M0 2h16v2H0V2zm0 5h16v2H0V7zm0 5h16v2H0v-2z" /></svg>); }
export function IconPlus({ className, size = 16 }: IconProps) { return (<svg className={className} width={size} height={size} viewBox="0 0 16 16" fill="currentColor" aria-hidden><path d="M7 0h2v16H7V0zM0 7h16v2H0V7z" /></svg>); }
export function IconRadio({ className, size = 16 }: IconProps) { return (<svg className={className} width={size} height={size} viewBox="0 0 16 16" fill="currentColor" aria-hidden><path d="M8 0a8 8 0 1 0 0 16A8 8 0 0 0 8 0zm0 4a4 4 0 1 1 0 8 4 4 0 0 1 0-8z" /></svg>); }
export function IconSearch({ className, size = 16 }: IconProps) { return (<svg className={className} width={size} height={size} viewBox="0 0 16 16" fill="currentColor" aria-hidden><path d="M10.5 9.5l4 4-1 1-4-4a5 5 0 1 1 1-1zM6 10a4 4 0 1 0 0-8 4 4 0 0 0 0 8z" /></svg>); }
export function IconSync({ className, size = 16 }: IconProps) { return (<svg className={className} width={size} height={size} viewBox="0 0 16 16" fill="currentColor" aria-hidden><path d="M12 4H4v2l-3-3 3-3v2h8c1.1 0 2 .9 2 2v4h-2V4zm-4 8h8v-2l3 3-3 3v-2H4c-1.1 0-2-.9-2-2v-4h2v6z" /></svg>); }
export function IconTrash({ className, size = 16 }: IconProps) { return (<svg className={className} width={size} height={size} viewBox="0 0 16 16" fill="currentColor" aria-hidden><path d="M5 1h6v1H5V1zM3 3h10v1H3V3zm1 2h8v9H4V5z" /></svg>); }
export function IconZap({ className, size = 16 }: IconProps) { return (<svg className={className} width={size} height={size} viewBox="0 0 16 16" fill="currentColor" aria-hidden><path d="M10 0L0 10h5v6l10-10H9l1-6z" /></svg>); }

