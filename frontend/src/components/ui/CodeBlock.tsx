import React from 'react';

interface CodeBlockProps {
  children?: React.ReactNode;
  className?: string;
  code?: string;
}

export const CodeBlock: React.FC<CodeBlockProps> = ({ children, className = '', code }) => {
  if (code) {
    // If raw string code is provided, render with syntax highlighting for python / openai sdk
    return (
      <pre
        className={`bg-ink text-[#E8E4FF] rounded-card p-7 font-mono text-[13.5px] leading-[1.8] overflow-x-auto shadow-xl ${className}`}
      >
        <code>{children || code}</code>
      </pre>
    );
  }

  return (
    <pre
      className={`bg-ink text-[#E8E4FF] rounded-card p-7 font-mono text-[13.5px] leading-[1.8] overflow-x-auto shadow-xl ${className}`}
    >
      <code>{children}</code>
    </pre>
  );
};
