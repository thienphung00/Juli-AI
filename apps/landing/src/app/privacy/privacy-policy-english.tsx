import { COMPANY } from "../../lib/site";

import { legal } from "./legal-template";

/**
 * The complete English version of /privacy (sections 1–12), rendered on the
 * same URL below the authoritative Vietnamese text. It is a faithful
 * translation: it must not make any claim the Vietnamese text does not make.
 * Google's OAuth brand-verification reviewers read this part.
 */

export const ENGLISH_SECTION_ID = "english";
export const ENGLISH_GOOGLE_SECTION_ID = "google-user-data";
export const LAST_UPDATED_EN = "October 18, 2026";
export const GOOGLE_USER_DATA_POLICY_URL =
  "https://developers.google.com/terms/api-services-user-data-policy";
export const GOOGLE_PERMISSIONS_URL = "https://myaccount.google.com/permissions";

function ContactLink() {
  return (
    <a href={`mailto:${COMPANY.email}`}>
      {COMPANY.email}
    </a>
  );
}

export function PrivacyPolicyEnglish() {
  return (
    <div
      className={legal.part}
      id={ENGLISH_SECTION_ID}
      lang="en"
      aria-labelledby="privacy-english-heading"
    >
      <h2 className={legal.partHeading} id="privacy-english-heading">
        Privacy Policy — Juli AI (English)
      </h2>
      <p className={legal.partUpdated}>
        Last updated (effective date): {LAST_UPDATED_EN}
      </p>

      <p className={legal.intro}>
        This policy explains how Juli AI collects, uses, shares and protects data when you
        use the website app-juli.com, the Demo and the Juli app, in accordance with the Law
        on Personal Data Protection No. 91/2025/QH15 and Decree 356/2025/NĐ-CP (Vietnam).
      </p>
      <p className={legal.intro}>
        This English version is a translation of the Vietnamese policy above. If the two
        versions differ, the Vietnamese version prevails, except where that would conflict
        with Juli AI&rsquo;s commitments under the Google API Services User Data Policy,
        including the Limited Use requirements (section 3), which always apply.
      </p>

      <section className={legal.section}>
        <h3 className={legal.sectionHeading}>1. Who we are</h3>
        <p>
          Juli AI is operated by <span lang="vi">{COMPANY.name}</span> (tax ID{" "}
          {COMPANY.taxId}), with its registered office at{" "}
          <span lang="vi">{COMPANY.address}</span>. <span lang="vi">{COMPANY.name}</span> is
          the controller and processor of the personal data described in this policy. For
          buyers&rsquo; personal data contained in shop data, however, the seller is the
          controller and Juli processes that data on the seller&rsquo;s behalf, under section
          8 of the <a href="/terms">Terms of Service</a>. For the de-identified data Juli uses
          to improve its own models (section 6), Juli is the controller.
        </p>
        <p>
          You can contact us by email at <ContactLink />.
        </p>
      </section>

      <section className={legal.section}>
        <h3 className={legal.sectionHeading}>2. Account information</h3>
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
        </ul>
        <h4 className={legal.subheading} id="free-trial-sign-up">
          Free-trial sign-up
        </h4>
        <p data-testid="privacy-trial-signup-en">
          When you sign up for the free trial on our <a href="/dang-ky">trial sign-up page</a>,
          we collect your name, phone/Zalo number, email address, TikTok shop name or link, your
          role, any note you write, how you reached us (utm parameters and referring page) and
          the time you gave consent. We do not store your IP address, only a hash of it to
          prevent repeated submissions and spam. We use this solely to contact you and set up
          your shop connection for the trial; only the Juli team can see it, and our email
          provider delivers the sign-up notice to the team. If you do not go on to use Juli, it
          is kept for at most 12 months from the sign-up date and then deleted; if you do, it
          becomes account information under this policy. You can ask us to delete it at any time
          at <ContactLink />; we delete it within 20 days.
        </p>
      </section>

      <section
        className={legal.section}
        id={ENGLISH_GOOGLE_SECTION_ID}
        aria-labelledby="google-user-data-heading-en"
      >
        <h3 className={legal.sectionHeading} id="google-user-data-heading-en">
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

        <h4 className={legal.subheading}>3.1. Data Juli accesses</h4>
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

        <h4 className={legal.subheading}>3.2. How Juli uses this data</h4>
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
          Google user data is also never used to train any of Juli&rsquo;s own models.
          Google user data is not sent to OpenAI or to any AI model. Juli staff do not read
          this data except with your consent (for example, when you ask for support, or to
          support and operate the service &mdash; which you accept when you connect a shop),
          when needed for security purposes (for example, investigating abuse), or when
          required by law. Staff see shop data only, never buyer data, and every access is
          logged.
        </p>

        <h4 className={legal.subheading}>3.3. Limited Use</h4>
        <p>
          Juli AI&rsquo;s use and transfer to any other app of information received from
          Google APIs will adhere to the{" "}
          <a
            href={GOOGLE_USER_DATA_POLICY_URL}
            rel="noopener noreferrer"
            target="_blank"
          >
            Google API Services User Data Policy
          </a>{" "}
          ({GOOGLE_USER_DATA_POLICY_URL}), including the Limited Use requirements.
        </p>

        <h4 className={legal.subheading}>3.4. Who Juli shares this data with</h4>
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

        <h4 className={legal.subheading}>3.5. How Juli protects this data</h4>
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

        <h4 className={legal.subheading}>
          3.6. Retention, deletion and revoking access
        </h4>
        <ul aria-label="Retention and deletion of Google user data">
          <li>
            Retention: Juli keeps the Google user data listed in section 3.1 for as long as
            your Juli account exists
          </li>
          <li>
            Deletion requests: email <ContactLink /> from your account&rsquo;s email address,
            or use Delete account in the app under Settings, Privacy. We respond within 2
            working days. When you delete your account, the account and all of its Google user
            data are deleted from Juli&rsquo;s systems and Supabase after 30 days, so you can
            download your data first; if you ask for immediate deletion, we delete within 20
            days of receiving the request
          </li>
          <li>
            Revoking access: you can remove Juli&rsquo;s access at any time on your{" "}
            <a
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

      <section className={legal.section}>
        <h3 className={legal.sectionHeading}>4. Information we read from your shop</h3>
        <p>
          After you connect your TikTok Shop shop, Juli periodically syncs the following data
          from the TikTok Shop API, to analyze your shop and make recommendations for it:
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
            Shop performance metrics provided by TikTok Shop (revenue, views, conversion rate
            by traffic source)
          </li>
          <li>Performance of the shop&rsquo;s videos and LIVEs, and the products tagged in them</li>
          <li>The shop&rsquo;s promotions and discount codes</li>
        </ul>
        <p>
          Juli does not read your personal messages, and does not store buyers&rsquo; contact
          information beyond the identifiers needed to process orders.
        </p>

        <h4 className={legal.subheading} id="content-you-provide">
          Content you provide
        </h4>
        <p>
          Besides the data read from the marketplace, Juli processes content you actively
          enter or upload: your shop&rsquo;s Rules (for example cost price, profit margin,
          tone of voice, banned words) and the videos or LIVE recordings you upload for Juli
          to analyze. Uploaded files are stored temporarily on Juli&rsquo;s server and deleted
          when the analysis ends; any file left over (for example an unfinished upload) is
          deleted automatically after about 24 hours. Juli keeps only the analysis results
          (for example the transcribed speech and scores). You warrant that you have the
          rights to this content, including the consent of the people who appear in it
          (section 8.4 of the <a href="/terms">Terms of Service</a>).
        </p>

        <h4 className={legal.subheading} id="buyer-reviews-and-market-data">
          Buyer reviews and market data
        </h4>
        <p>
          If Juli uses the text of buyers&rsquo; product reviews (for example to understand
          how buyers describe a product), Juli removes the buyer&rsquo;s name and identifying
          information before processing it, including before sending it to an AI model.
        </p>
        <p>
          Market and competitor data (for example selling prices, best-selling products and
          videos by category, keywords) comes from public sources and from FastMoss, a TikTok
          Shop market data provider. Juli collects this data itself; it does not come from
          the private data of other shops that use Juli. Juli does not send your shop data
          (orders, business figures, buyer data) to FastMoss; when looking data up, Juli uses
          only information that is already public on TikTok Shop, such as a shop or product
          name.
        </p>
      </section>

      <section className={legal.section} id="shopee-data-en">
        <h3 className={legal.sectionHeading}>
          4A. Shopee data (when you connect a Shopee shop)
        </h3>
        <p>
          Shopee is being integrated through Shopee Open Platform. This section takes effect
          when you connect a Shopee shop to Juli; until then, Juli reads no data from Shopee.
        </p>
        <p>
          After you connect and authorize, Juli reads through Shopee Open Platform: shop
          information, products/listings, orders and the performance metrics needed to
          analyze your shop and make recommendations for it, similar to the TikTok Shop data
          in section 4. Buyers&rsquo; personal information is processed only as far as needed
          to process orders, and Juli staff see shop data only, not buyer data (section 3).
        </p>
        <p>
          Purpose and retention are the same as for TikTok Shop data (sections 6 and 8): data
          is kept while you use Juli, syncing stops immediately when you disconnect the
          shop, and data is deleted as described in section 8 when you delete your account. Juli
          adheres to the Shopee Open Platform Data Protection Policy. Changes to your Shopee
          shop are written only after you have actively approved them.
        </p>
      </section>

      <section className={legal.section}>
        <h3 className={legal.sectionHeading}>
          5. What Juli records or changes on your shop
        </h3>
        <p>
          By default, Juli does not change anything on your live TikTok Shop shop. Trial
          actions (for example, creating a product discount code) run in the test environment
          (sandbox) provided by TikTok, separate from your live shop.
        </p>
        <p>
          An action on your live shop is carried out only when (a) you have actively approved
          that recommendation, and (b) write permission has been granted separately for
          exactly one product and exactly one type of action, is time-limited, and can be
          used only once.
        </p>
      </section>

      <section className={legal.section}>
        <h3 className={legal.sectionHeading}>6. Purposes of data use</h3>
        <h4 className={legal.subheading}>6.1. Providing the service</h4>
        <ul>
          <li>To provide, operate and secure your Juli account and the Juli service</li>
          <li>To analyze shop performance and create optimization recommendations for your shop</li>
          <li>To send the alerts and notifications you have turned on</li>
          <li>To provide support and announce important changes to the service and its terms</li>
        </ul>
        <p>
          Script, title and content suggestions are processed separately for each shop, based
          on that shop&rsquo;s own data and wording; a shop&rsquo;s own content is not shown to
          other shops and is not used to create suggestions for other shops, except in
          de-identified form under section 6.2.
        </p>
        <h4 className={legal.subheading}>6.2. Improving Juli&rsquo;s algorithms and models</h4>
        <p>
          Juli uses data to analyze, optimize its algorithms, research, train, fine-tune, test
          and develop Juli&rsquo;s models and services, under these principles:
        </p>
        <ul aria-label="Principles for using data to improve Juli">
          <li>
            De-identified data only: shop data (sections 4, 4A) and data about how you use Juli
            are stripped of the shop name, shop ID, your name, email, phone number and any
            information that could identify you, your shop or any individual before they are
            used for this purpose.
          </li>
          <li>
            A condition of using Juli, under section 8.6 of the{" "}
            <a href="/terms">Terms of Service</a>. Personal data that still identifies you is
            never used to train models.
          </li>
          <li>
            Buyer data and Google user data are never used to train models. Buyers&rsquo;
            personal data is anonymized before it enters any analysis pipeline.
          </li>
          <li>
            Data used for this purpose is not disclosed to other customers. Data already used
            for training cannot be separated from the model; when you delete your account, the
            original data is deleted as described in section 8, but Juli does not retrain those
            models.
          </li>
        </ul>
        <p>
          Under Decree 356/2025/NĐ-CP, data about a person&rsquo;s online behaviour and service
          usage habits is sensitive personal data. Juli uses it in a form linked to you only to
          operate and support your account; it is de-identified before use under section 6.2.
        </p>
        <h4 className={legal.subheading}>6.3. Marketing and ad measurement (you can opt out)</h4>
        <ul>
          <li>To send news about Juli features and offers</li>
          <li>To measure the effectiveness of Juli&rsquo;s advertising on TikTok</li>
          <li>To name or show your shop&rsquo;s logo as a customer example, only if you turn this on</li>
        </ul>
        <p>You turn each of these on or off in the app under Settings, Privacy.</p>
        <p>
          Juli stores, analyzes and shares your data only for the purposes above. Juli does
          not sell data, and does not use data that can identify your shop to serve other
          customers.
        </p>
      </section>

      <section className={legal.section}>
        <h3 className={legal.sectionHeading}>7. Who we share data with</h3>
        <p>
          Juli does not sell your data to any third party, and does not disclose or transfer
          your data beyond the parties below. We share data only with the following data
          processors, each receiving only the data its role requires:
        </p>
        <ul aria-label="Data processors">
          <li>
            Supabase — sign-in authentication (Google and email verification codes) and
            database hosting
          </li>
          <li>
            TikTok Shop API — the source of your shop data; Shopee Open Platform — when you
            connect a Shopee shop (section 4A)
          </li>
          <li>
            OpenAI — the provider of the AI (language) models Juli uses to analyze shop data
            and create recommendations (details below)
          </li>
          <li>
            Server (VPS) provider — where the Juli app runs and where files you upload for
            analysis are stored temporarily
          </li>
          <li>
            Cloudflare — domain management, routing and protection of connections (HTTPS) to
            app-juli.com and its subdomains; access control for the Juli team&rsquo;s internal
            tool
          </li>
          <li>Amazon Web Services (AWS) — management of system secret keys</li>
          <li>
            Google Workspace — the email service Juli uses to send you sign-in codes,
            notifications and account messages
          </li>
          <li>
            Zalo (Zalo OA) and Google Firebase (planned) — sending alerts and push
            notifications, only if you turn them on
          </li>
          <li>
            Viettel-CA (planned) — issuing, sending and storing e-invoices when you pay, and
            transmitting invoice data to the tax authority as required
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
          FastMoss (section 4) is a market data source Juli looks data up in, not a processor
          of your shop data.
        </p>

        <h4 className={legal.subheading} id="ai-provider">
          Data sent to the AI provider (OpenAI)
        </h4>
        <p>
          Juli uses OpenAI&rsquo;s models through the OpenAI API, a service for businesses and
          developers, not through the consumer ChatGPT app. The specific model may change
          among OpenAI&rsquo;s models. Juli sends only the data each analysis needs:
        </p>
        <ul aria-label="Data sent to OpenAI">
          <li>Product information (name, description, category, price) and shop performance figures</li>
          <li>Product images, to check that an image matches the product&rsquo;s content</li>
          <li>The Rules and content you enter (for example tone of voice, banned words)</li>
          <li>
            For videos or LIVE recordings you upload: extracted frames (small images) and
            audio segments for speech-to-text; Juli never sends the whole file
          </li>
          <li>The text of buyer reviews, if used, after buyer identifiers have been removed</li>
        </ul>
        <p>
          Juli does not send OpenAI buyers&rsquo; contact information or identifiers, Google
          user data, or marketplace account sign-in details. Under OpenAI&rsquo;s API terms and
          data policy, data sent through the API is not used by OpenAI to train OpenAI&rsquo;s
          models. Juli sends its analysis requests with OpenAI&rsquo;s response storage turned
          off; under OpenAI&rsquo;s API data policy, OpenAI may still keep API data for a
          limited period to monitor for abuse. A fine-tuned model (if any) is Juli&rsquo;s own
          model and uses only data de-identified as described in section 6.2. Juli limits the
          scope and volume of model use for each shop.
        </p>

        <h4 className={legal.subheading} id="cross-border-transfer">
          Transfers outside Vietnam
        </h4>
        <p>
          Some of the processors above (for example OpenAI and Amazon Web Services) process
          or store data outside Vietnam, mainly in the United States, so data may be
          transferred abroad. We transfer only the data necessary for the purposes in section
          6, and protect it by: using only providers that operate under their terms of
          service and data protection commitments; encrypting data in transit (HTTPS/TLS);
          sending only the data each task needs; and removing buyer identifiers before
          anything is sent to an AI model. We may also provide data when a competent
          government authority requests it in accordance with the law.
        </p>
      </section>

      <section className={legal.section}>
        <h3 className={legal.sectionHeading}>8. Security and retention</h3>
        <p>
          Data is encrypted in transit (HTTPS/TLS) and encrypted at rest by our database
          provider (Supabase). Access to data is limited per account and per shop, and TikTok
          Shop access keys are kept in a managed secret store, not in source code. Details
          specific to Google user data are in sections 3.5 and 3.6.
        </p>
        <p>
          If we discover a data leak or loss that affects your data, Juli notifies you no
          later than 72 hours after discovering it.
        </p>
        <p>
          We keep data for as long as you use Juli. When you disconnect a shop, Juli
          immediately stops syncing new data from that shop. When you delete your account,
          Juli stops syncing shop data and keeps the data for 30 more days so you can download
          it or cancel; your account data and shop data are then deleted. If you ask for
          immediate deletion, we delete within 20 days. Invoices and accounting records are
          kept for 10 years under accounting law; de-identified data under section 6.2 is not
          deleted.
        </p>
      </section>

      <section className={legal.section}>
        <h3 className={legal.sectionHeading}>9. Your rights</h3>
        <p>Under the Law on Personal Data Protection, you have the right to:</p>
        <ul>
          <li>Be informed about the processing of your personal data</li>
          <li>Access, view and request correction of your personal data</li>
          <li>Request an exported copy of your data</li>
          <li>Request deletion of your data or restriction of its processing</li>
          <li>
            Withdraw your consent and object to processing (for example, by disconnecting your
            shop or turning off alerts)
          </li>
          <li>Opt out of marketing and ad measurement, and of your shop being named as a customer example</li>
          <li>Complain, sue and claim compensation as provided by law</li>
        </ul>
        <p>
          You can exercise these rights in the app under Settings, Privacy (turn off marketing
          and ad measurement, download your data, delete your account), or by sending a request
          to <ContactLink />. We respond within 2 working days. Requests to withdraw consent,
          restrict or object to processing are carried out within 15 days; requests to view,
          correct or export data within 10 days; deletion requests within 20 days.
        </p>
        <p>
          Some data is necessary for Juli to work (section 6.1) or is a condition of use
          (section 6.2). If you withdraw consent for, or ask us to delete, that data, Juli can
          no longer provide the service and your account ends under the{" "}
          <a href="/terms">Terms of Service</a>. Withdrawing consent does not affect processing
          carried out before.
        </p>
      </section>

      <section className={legal.section}>
        <h3 className={legal.sectionHeading}>10. Age requirement</h3>
        <p>
          Juli is a service for sellers, household businesses and businesses using it for
          business purposes. You must be 18 or older to use Juli.
          We do not knowingly collect data from anyone under 18.
        </p>
      </section>

      <section className={legal.section}>
        <h3 className={legal.sectionHeading}>11. Changes to this policy</h3>
        <p>
          When this policy changes, we update the date at the top of this page and notify you
          by email and in the app at least 15 days before the change takes effect. Continuing
          to use Juli after that date means you accept the new policy. If Juli changes how it accesses, uses, stores or shares Google user data,
          we will notify you and ask for your consent again before applying the change.
        </p>
      </section>

      <section className={legal.section}>
        <h3 className={legal.sectionHeading}>12. Contact</h3>
        <p>
          For any questions about this policy, please contact{" "}
          <span lang="vi">{COMPANY.name}</span> at <ContactLink />.
        </p>
      </section>
    </div>
  );
}
