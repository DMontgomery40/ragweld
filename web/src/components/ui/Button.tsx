import React from "react";

type ButtonVariant = "primary" | "secondary" | "ghost";
type ButtonSize = "sm" | "md" | "lg";

export type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
  leftIcon?: React.ReactNode;
  rightIcon?: React.ReactNode;
  fullWidth?: boolean;
};

function cx(...classes: Array<string | false | null | undefined>): string {
  return classes.filter(Boolean).join(" ");
}

const base =
  // layout + typography
  "inline-flex items-center justify-center font-medium select-none whitespace-nowrap" +
  // sizing handled by size map
  "" +
  // border + radius
  " rounded-xl border" +
  // transitions
  " transition-colors duration-200 ease-out" +
  // focus-visible ring (accessibility)
  " focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-accent focus-visible:ring-offset-bg" +
  // disabled state
  " disabled:opacity-50 disabled:pointer-events-none";

const variants: Record<ButtonVariant, string> = {
  primary:
    // neon accent on near-black background
    " bg-accent text-black border-transparent hover:brightness-110 active:brightness-95",
  secondary:
    // subtle outline with neon text
    " bg-transparent text-accent border-accent/60 hover:bg-accent/10 active:bg-accent/20",
  ghost:
    // text-only, minimal chrome
    " bg-transparent text-accent border-transparent hover:bg-accent/10 active:bg-accent/20",
};

const sizes: Record<ButtonSize, string> = {
  sm: " h-8 px-3 text-[13px] gap-2",
  md: " h-10 px-4 text-[14px] gap-2.5",
  lg: " h-12 px-5 text-[15px] gap-3",
};

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      variant = "primary",
      size = "md",
      leftIcon,
      rightIcon,
      fullWidth,
      className,
      children,
      ...rest
    },
    ref
  ) => {
    return (
      <button
        ref={ref}
        className={cx(
          base,
          variants[variant],
          sizes[size],
          fullWidth && "w-full",
          // high-contrast selection safety on neon themes
          "selection:bg-white selection:text-black",
          className
        )}
        {...rest}
      >
        {leftIcon ? <span aria-hidden="true" className="-ml-0.5">{leftIcon}</span> : null}
        <span>{children}</span>
        {rightIcon ? <span aria-hidden="true" className="-mr-0.5">{rightIcon}</span> : null}
      </button>
    );
  }
);

Button.displayName = "Button";

