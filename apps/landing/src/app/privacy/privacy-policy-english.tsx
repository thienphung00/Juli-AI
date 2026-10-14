import { COMPANY } from "../../lib/site";

/**
 * The complete English version of /privacy (sections 1–12), rendered on the
 * same URL below the authoritative Vietnamese text. It is a faithful
 * translation: it must not make any claim the Vietnamese text does not make.
 * Google's OAuth brand-verification reviewers read this part.
 */

export const ENGLISH_SECTION_ID = "english";
export const ENGLISH_GOOGLE_SECTION_ID = "google-user-data";
export const VERSION_EN = "2.0";
export const LAST_UPDATED_EN = "October 14, 2026";
export const GOOGLE_USER_DATA_POLICY_URL =
  "https://developers.google.com/terms/api-services-user-data-policy";
export const GOOGLE_PERMISSIONS_URL = "https://myaccount.google.com/permissions";

function ContactLink() {
  return (
    <a className="lp-legal__contact-link" href={`mailto:${COMPANY.email}`}>
      {COMPANY.email}
    </a>
  );
}

export function PrivacyPolicyEnglish() {
  return (
    <div
      className="lp-legal__part"
      id={ENGLISH_SECTION_ID}
      lang="en"
      aria-labelledby="privacy-english-heading"
    >
      <h2 className="lp-legal__heading" id="privacy-english-heading">
        Privacy Policy — Juli AI (English)
      </h2>
      <p className="lp-legal__updated">
        Version: {VERSION_EN} — Last updated (effective date): {LAST_UPDATED_EN}
      </p>

      <p className="lp-legal__intro">
        This policy explains how Juli AI collects, uses, shares and protects data when you
        use the website app-juli.com, the Demo and the Juli app, in accordance with the Law
        on Personal Data Protection (Vietnam) and its implementing regulations.
      </p>
      <p className="lp-legal__intro">
        This English version is a translation of the Vietnamese policy above. If the two
        versions differ, the Vietnamese version prevails, except where that would conflict
        with Juli AI&rsquo;s commitments under the Google API Services User Data Policy,
        including the Limited Use requirements (section 3), which always apply.
      </p>

      <section className="lp-legal__section">
        <h3 className="lp-legal__section-heading">1. Who we are</h3>
        <p>
          Juli AI is operated by <span lang="vi">{COMPANY.name}</span> (tax ID{" "}
          {COMPANY.taxId}), with its registered office at{" "}
          <span lang="vi">{COMPANY.address}</span>. <span lang="vi">{COMPANY.name}</span> is
          the controller and processor of the personal data described in this policy. For
          buyers&rsquo; personal data contained in shop data, however, the seller is the
          controller and Juli processes that data on the seller&rsquo;s behalf, under section
          10 of the{" "}
          <a className="lp-legal__contact-link" href="/terms">
            Terms of Service
          </a>
          .
        </p>
        <p>
          You can contact us by email at <ContactLink />.
        </p>
      </section>

      <section className="lp-legal__section">
        <h3 className="lp-legal__section-heading">2. Account information</h3>
        <p>
          You create and access your Juli account by signing in with Google, or with your
          email address and a verification code sent to your inbox (via Supabase Auth). We
          do not ask you to create or enter a password.
        </p>
        <ul aria-label="Account information Juli collects">
          <li>
            From Google: email address, display name, profile picture and Google account ID
            (see section 3)
          </li>
          <li>When you sign in with email: the email address you enter</li>
          <li>
            Optional: your Zalo phone number or Zalo user ID, only if you turn on Zalo alerts
          </li>
          <li>Optional: a device token, only if you turn on push notifications on your phone</li>
          <li>
            Invoicing information: business/household business name or your full name, tax
            ID or personal identification number, address, and the email address for
            invoices &mdash; only when you pay
          </li>
        </ul>
      </section>

      <section
        className="lp-legal__section"
        id={ENGLISH_GOOGLE_SECTION_ID}
        aria-labelledby="google-user-data-heading-en"
      >
        <h3 className="lp-legal__section-heading" id="google-user-data-heading-en">
          3. Google user data
        </h3>
        <p>
          This section applies when you choose &ldquo;Sign in with Google&rdquo; on Juli AI
          (app-juli.com and demo.app-juli.com), operated by{" "}
          <span lang="vi">{COMPANY.name}</span>. Sign-in is handled through Supabase Auth.
          Juli requests only Google&rsquo;s basic sign-in scopes: <strong>openid</strong>,{" "}
          <strong>email</strong> and <strong>profile</strong>. Juli does not request access
          to Gmail, Google Drive, Contacts, Calendar or any other Google service or data.
        </p>

        <h4 className="lp-legal__subheading">3.1. Data Juli accesses</h4>
        <ul aria-label="Google user data Juli accesses">
          <li>Your Google account email address and whether that email is verified</li>
          <li>Your display name (full name) on your Google account</li>
          <li>Your profile picture (profile image URL) on your Google account</li>
          <li>Your Google account ID</li>
        </ul>
        <p>
          Juli never receives your Google password. Juli does not store your Google access
          token or refresh token, and does not call any Google API on your behalf after you
          sign in.
        </p>

        <h4 className="lp-legal__subheading">3.2. How Juli uses this data</h4>
        <ul aria-label="How Juli uses Google user data">
          <li>To create your Juli account and sign you in on later visits</li>
          <li>
            To identify your account, so that each account can see only its own shops and
            data, and to show you which email you are signed in with inside the app
          </li>
          <li>
            To contact you about your Juli account and the Juli service (for example,
            support or important changes)
          </li>
        </ul>
        <p>
          Juli uses Google user data only to provide and improve the user-facing features of
          Juli that you see and use. Juli does <strong>not</strong> use this data for
          advertising (including targeted, personalized or retargeted advertising), does{" "}
          <strong>not</strong> sell this data, does <strong>not</strong> use it for credit
          assessment or lending, and does <strong>not</strong> use it to develop, improve or
          train generalized artificial intelligence (AI) or machine learning (ML) models.
          Google user data is not sent to OpenAI or to any AI model. Juli staff do not read
          this data except with your consent (for example, when you ask for support, or to
          support and operate the service &mdash; which you accept when you connect a shop),
          when needed for security purposes (for example, investigating abuse), or when
          required by law. Staff view only the shop data needed for support, do not copy or
          store buyer data, and every access is logged.
        </p>

        <h4 className="lp-legal__subheading">3.3. Limited Use</h4>
        <p>
          Juli AI&rsquo;s use and transfer to any other app of information received from
          Google APIs will adhere to the{" "}
          <a
            className="lp-legal__contact-link"
            href={GOOGLE_USER_DATA_POLICY_URL}
            rel="noopener noreferrer"
            target="_blank"
          >
            Google API Services User Data Policy
          </a>{" "}
          ({GOOGLE_USER_DATA_POLICY_URL}), including the Limited Use requirements.
        </p>

        <h4 className="lp-legal__subheading">3.4. Who Juli shares this data with</h4>
        <p>
          Juli does not sell, rent or trade Google user data. Juli transfers or discloses
          this data only in the following cases:
        </p>
        <ul aria-label="Recipients of Google user data">
          <li>
            Service providers needed to operate Juli, only to the extent necessary: Supabase
            (sign-in authentication and hosting of Juli&rsquo;s database), the server (VPS)
            provider that runs the Juli app, and Google Workspace (the email service Juli
            uses to send you sign-in codes and account-related emails)
          </li>
          <li>When required by law or by a competent government authority</li>
          <li>With your explicit consent</li>
        </ul>
        <p>
          Juli does not send Google user data to any advertising platform (including TikTok
          Pixel and the TikTok Events API), does not send it to data brokers, and does not
          transfer it to any other party for any purpose other than those listed above.
        </p>

        <h4 className="lp-legal__subheading">3.5. How Juli protects this data</h4>
        <ul aria-label="How Juli protects Google user data">
          <li>
            Encryption in transit: connections between your browser and Juli, and between
            Juli&rsquo;s servers and Supabase, are encrypted with HTTPS/TLS
          </li>
          <li>
            The database is hosted on Supabase, where data is encrypted at rest by the
            provider
          </li>
          <li>
            Access control: every request to Juli&rsquo;s servers must carry a signed-in
            session whose signature has been verified; the database enforces row-level
            security so that each account can read only its own data; the app runs with a
            database account that has only the minimum privileges it needs
          </li>
          <li>
            System secret keys are kept in a managed secret store (AWS), not in source code
          </li>
          <li>
            Your browser stores only your Juli session (issued by Supabase), not any Google
            access token; this session is deleted when you sign out
          </li>
        </ul>

        <h4 className="lp-legal__subheading">
          3.6. Retention, deletion and revoking access
        </h4>
        <ul aria-label="Retention and deletion of Google user data">
          <li>
            Retention: Juli keeps the Google user data listed in section 3.1 for as long as
            your Juli account exists
          </li>
          <li>
            Deletion requests: email <ContactLink /> from your account&rsquo;s email address.
            We confirm within 72 hours and delete your account and all of its Google user
            data from Juli&rsquo;s systems and Supabase within 30 days of receiving the
            request
          </li>
          <li>
            Revoking access: you can remove Juli&rsquo;s access at any time on your{" "}
            <a
              className="lp-legal__contact-link"
              href={GOOGLE_PERMISSIONS_URL}
              rel="noopener noreferrer"
              target="_blank"
            >
              Google Account permissions page
            </a>{" "}
            (myaccount.google.com/permissions). After you revoke access, Juli can no longer
            sign you in with Google. Revoking access does not automatically delete the data
            Juli has stored; to delete it, send a deletion request as described above
          </li>
        </ul>
      </section>

      <section className="lp-legal__section">
        <h3 className="lp-legal__section-heading">4. Information we read from your shop</h3>
        <p>
          Juli supports shops on TikTok Shop and Shopee. Juli accesses shop data in one of two
          ways, depending on the marketplace and on your choice:
        </p>
        <ul aria-label="How Juli accesses shop data">
          <li>
            (a) Official authorization through the marketplace&rsquo;s API: you click an
            authorization link, the marketplace shows the list of permissions Juli requests,
            and you approve them. This applies to TikTok Shop, and to Shopee once Juli&rsquo;s
            app has been approved by Shopee.
          </li>
          <li>
            (b) A sub-account you provide: you create a sub-account in the
            marketplace&rsquo;s Seller Center (for example, Shopee), choose that
            sub-account&rsquo;s permission scope yourself, and give it to Juli. You can
            change the password, narrow the permissions or lock the sub-account at any time.
            Juli keeps the sub-account&rsquo;s login credentials confidential, uses the
            sub-account only to serve your shop, and does not share it with third parties.
          </li>
        </ul>
        <p>
          Juli periodically reads the following data, to analyze your shop and make
          recommendations for it:
        </p>
        <ul aria-label="Shop data Juli reads">
          <li>
            Orders and the details of each order (order ID, status, value, payment/delivery
            times)
          </li>
          <li>Products (name, category, selling price, revenue, quantity sold)</li>
          <li>Inventory per product/SKU and warehouse</li>
          <li>Returns/cancellations (return type, reason, refund amount)</li>
          <li>
            Shop performance metrics provided by the marketplace (revenue, views, conversion
            rate by traffic source)
          </li>
          <li>Performance of the shop&rsquo;s videos and LIVEs, and the products tagged in them</li>
          <li>The shop&rsquo;s promotions, discount codes and advertising metrics</li>
        </ul>
        <p>
          Juli does not read your personal messages, and does not collect or store
          buyers&rsquo; contact information (name, phone number, address) beyond the
          identifiers needed to process orders &mdash; even when that information is visible
          in the Seller Center that the sub-account has permission to view.
        </p>
      </section>

      <section className="lp-legal__section">
        <h3 className="lp-legal__section-heading">
          5. What Juli records or changes on your shop
        </h3>
        <p>
          By default, Juli only reads data and does not change anything on your live shop.
          Trial actions (for example, creating a product discount code) run in the test
          environment (sandbox) provided by the marketplace, where available, separate from
          your live shop.
        </p>
        <p>
          An action on your live shop is carried out only when (a) you have actively approved
          that recommendation, and (b) the action is limited to exactly the products and
          exactly the type of action you approved. With an API connection, each action uses
          a separate write permission that is time-limited and can be used only once. With a
          sub-account, Juli carries out only the action you approved, within the permissions
          you granted to that sub-account.
        </p>
      </section>

      <section className="lp-legal__section">
        <h3 className="lp-legal__section-heading">6. Purposes of data use</h3>
        <ul>
          <li>To provide, operate and secure your Juli account and the Juli service</li>
          <li>To analyze shop performance and create optimization recommendations for your shop</li>
          <li>To send the alerts and notifications you have turned on</li>
          <li>To measure the effectiveness of Juli&rsquo;s advertising on TikTok</li>
          <li>To provide support and announce important changes to the service</li>
          <li>
            To issue invoices, keep payment records and meet accounting and tax obligations
            as required by law
          </li>
          <li>
            To optimize Juli&rsquo;s analysis algorithms and the quality of its suggestions,
            including fine-tuning a language model, using only anonymized data in structured
            form (see below)
          </li>
        </ul>
        <p>
          For algorithm optimization, Juli uses only anonymized shop data, and only in
          structured form (for example, metric types, correlations between metrics,
          recommendation types and the results after they were applied). This data does not
          contain shop names, product names or content, images, scripts, titles, business
          figures that could identify a shop, buyer information or Google user data, and it
          is not disclosed to other customers. You can ask us to stop using your data for
          this purpose at any time by emailing <ContactLink />.
        </p>
        <p>
          Script, title and content suggestions are processed separately for each shop, based
          on that shop&rsquo;s own data and wording; a shop&rsquo;s own content is used only
          to create suggestions for that same shop.
        </p>
      </section>

      <section className="lp-legal__section">
        <h3 className="lp-legal__section-heading">7. Who we share data with</h3>
        <p>
          Juli does not sell, disclose or transfer your data to any third party, and does
          not use your data for any other purpose (including not using data that could
          identify your shop to serve other customers). We share data only with the following
          data processors, to the extent necessary to operate the product:
        </p>
        <ul aria-label="Data processors">
          <li>Supabase — sign-in authentication (Google) and database hosting</li>
          <li>
            TikTok Shop API and Shopee (API or Seller Center) — the source of your shop data
          </li>
          <li>
            OpenAI — a third-party language model (AI) used to analyze shop data and create
            recommendations. Juli sends OpenAI only the shop information that the marketplace
            (TikTok Shop, Shopee) has granted access to, at the level needed for each
            analysis; it does not send buyers&rsquo; contact information and does not send
            Google user data. Data sent through OpenAI&rsquo;s API is not used by OpenAI to
            train OpenAI&rsquo;s general models and is retained only temporarily under
            OpenAI&rsquo;s API data policy; a fine-tuned model (if any) is Juli&rsquo;s own
            model and uses only the anonymized data described in section 6. Juli limits the
            scope and level of model usage for each account
          </li>
          <li>Server (VPS) provider — where the Juli app runs</li>
          <li>Amazon Web Services (AWS) — management of system secret keys</li>
          <li>
            Zalo (Zalo OA) and Google Firebase — sending the alerts and push notifications you
            have turned on
          </li>
          <li>
            Viettel-CA — issuing, sending and storing electronic invoices, and transmitting
            invoice data to the tax authority as required by law
          </li>
          <li>
            TikTok Pixel and Events API — measuring advertising effectiveness. They receive
            your IP address, browser information, the pages you view on this website, and
            TikTok&rsquo;s advertising identifier if you arrived from an ad. If you sign up,
            TikTok receives only your hashed (SHA-256) Juli user ID — not your email or any
            Google user data
          </li>
        </ul>
        <p>
          Some of the processors above host their servers outside Vietnam (for example, in
          the United States), so data may be transferred abroad. We transfer only the data
          necessary for the purposes in section 6. We may also provide data when a competent
          government authority requests it in accordance with the law.
        </p>
      </section>

      <section className="lp-legal__section">
        <h3 className="lp-legal__section-heading">8. Security and retention</h3>
        <p>
          Data is encrypted in transit (HTTPS/TLS) and encrypted at rest by our database
          provider (Supabase). Access to data is limited per account and per shop.
          Marketplace access keys and sub-account login credentials are kept in a managed
          secret store, not in source code. Details specific to Google user data are in
          sections 3.5 and 3.6.
        </p>
        <p>
          Juli strictly complies with TikTok Shop&rsquo;s and Shopee&rsquo;s policies on data
          access, processing and protection: it accesses data only within the permissions you
          have granted and as needed for analysis, and does not store data outside
          Juli&rsquo;s systems.
        </p>
        <p>
          We keep data for as long as you use Juli. When you disconnect a shop or lock the
          sub-account, Juli immediately stops syncing new data from that shop, and deletes
          the shop data already synced within 30 days. When you request account deletion,
          your account data and shop data are deleted within 30 days, except data the law
          requires us to keep: invoices, payment records and invoicing information are kept
          for the period required by accounting law (at least 10 years).
        </p>
      </section>

      <section className="lp-legal__section">
        <h3 className="lp-legal__section-heading">9. Your rights</h3>
        <p>Under personal data protection law, you have the right to:</p>
        <ul>
          <li>Be informed about and access your personal data</li>
          <li>Request correction of inaccurate data</li>
          <li>Request an exported copy of your data</li>
          <li>Request deletion of your data or restriction of its processing</li>
          <li>
            Withdraw your consent at any time (for example, by disconnecting your shop,
            locking the sub-account or turning off alerts)
          </li>
          <li>Complain about the processing of your data</li>
        </ul>
        <p>
          To exercise these rights, send a request to <ContactLink />. We respond within 72
          hours.
        </p>
      </section>

      <section className="lp-legal__section">
        <h3 className="lp-legal__section-heading">10. Age requirement</h3>
        <p>
          Juli is a service for sellers and businesses. You must be 18 or older to use Juli.
          We do not knowingly collect data from anyone under 18.
        </p>
      </section>

      <section className="lp-legal__section">
        <h3 className="lp-legal__section-heading">11. Changes to this policy</h3>
        <p>
          When this policy changes, we update the version number and date at the top of
          this page. For
          significant changes, we notify you by email at least 7 days before the change takes
          effect. If Juli changes how it accesses, uses, stores or shares Google user data,
          we will notify you and ask for your consent again before applying the change.
        </p>
      </section>

      <section className="lp-legal__section">
        <h3 className="lp-legal__section-heading">12. Contact</h3>
        <p>
          For any questions about this policy, please contact{" "}
          <span lang="vi">{COMPANY.name}</span> at <ContactLink />.
        </p>
      </section>
    </div>
  );
}
