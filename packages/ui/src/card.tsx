import type { ComponentPropsWithoutRef, ReactNode } from "react";

export interface CardProps extends ComponentPropsWithoutRef<"article"> {
  children: ReactNode;
}

export function Card({ className, children, ...rest }: CardProps) {
  const classNames = ["juli-card", className].filter(Boolean).join(" ");

  return (
    <article className={classNames} {...rest}>
      {children}
    </article>
  );
}

export interface CardHeaderProps extends ComponentPropsWithoutRef<"header"> {
  children: ReactNode;
}

export function CardHeader({ className, children, ...rest }: CardHeaderProps) {
  const classNames = ["juli-card__header", className].filter(Boolean).join(" ");

  return (
    <header className={classNames} {...rest}>
      {children}
    </header>
  );
}

export interface CardTitleProps extends ComponentPropsWithoutRef<"h3"> {
  children: ReactNode;
  id?: string;
}

export function CardTitle({ className, children, ...rest }: CardTitleProps) {
  const classNames = ["juli-card__title", className].filter(Boolean).join(" ");

  return (
    <h3 className={classNames} {...rest}>
      {children}
    </h3>
  );
}

export interface CardMetaProps extends ComponentPropsWithoutRef<"span"> {
  children: ReactNode;
}

export function CardMeta({ className, children, ...rest }: CardMetaProps) {
  const classNames = ["juli-card__meta", className].filter(Boolean).join(" ");

  return (
    <span className={classNames} {...rest}>
      {children}
    </span>
  );
}

export interface CardBodyProps extends ComponentPropsWithoutRef<"div"> {
  children: ReactNode;
}

export function CardBody({ className, children, ...rest }: CardBodyProps) {
  const classNames = ["juli-card__body", className].filter(Boolean).join(" ");

  return (
    <div className={classNames} {...rest}>
      {children}
    </div>
  );
}

export interface CardFooterProps extends ComponentPropsWithoutRef<"footer"> {
  children: ReactNode;
}

export function CardFooter({ className, children, ...rest }: CardFooterProps) {
  const classNames = ["juli-card__footer", className].filter(Boolean).join(" ");

  return (
    <footer className={classNames} {...rest}>
      {children}
    </footer>
  );
}

type InteractiveCardBaseProps = {
  children: ReactNode;
  className?: string;
  "data-testid"?: string;
};

export type InteractiveCardProps =
  | (InteractiveCardBaseProps &
      Omit<ComponentPropsWithoutRef<"button">, "children" | "className"> & {
        href?: undefined;
      })
  | (InteractiveCardBaseProps &
      Omit<ComponentPropsWithoutRef<"a">, "children" | "className"> & {
        href: string;
      });

export function InteractiveCard(props: InteractiveCardProps) {
  const { children, className, "data-testid": dataTestId } = props;
  const classNames = ["juli-card", "juli-card--interactive", className]
    .filter(Boolean)
    .join(" ");

  if ("href" in props && props.href) {
    const { href, children: _children, className: _className, ...rest } = props;

    return (
      <a
        className={classNames}
        data-testid={dataTestId}
        href={href}
        {...rest}
      >
        {children}
      </a>
    );
  }

  const {
    children: _children,
    className: _className,
    type = "button",
    ...rest
  } = props as InteractiveCardBaseProps &
    Omit<ComponentPropsWithoutRef<"button">, "children" | "className">;

  return (
    <button
      className={classNames}
      data-testid={dataTestId}
      type={type}
      {...rest}
    >
      {children}
    </button>
  );
}
