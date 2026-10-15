import { NEXT_STEPS } from "./signup-content";
import styles from "./signup.module.css";

/** The 3 numbered steps after a sign-up (ink circles, Signup.dc.html). */
export function NextSteps({ level = 3 }: { readonly level?: 2 | 3 }) {
  const Title = `h${level}` as "h2" | "h3";
  return (
    <ol className={styles.steps} data-testid="signup-next-steps">
      {NEXT_STEPS.map((step, index) => (
        <li className={styles.step} key={step.title}>
          <span aria-hidden="true" className={styles.stepNum}>
            {index + 1}
          </span>
          <div>
            <Title className={styles.stepTitle}>{step.title}</Title>
            <p className={styles.stepBody}>{step.body}</p>
          </div>
        </li>
      ))}
    </ol>
  );
}
