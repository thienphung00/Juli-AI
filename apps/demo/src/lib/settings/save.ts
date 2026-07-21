let shouldFailSave = false;

export function setSettingsSaveFailureForTest(enabled: boolean) {
  shouldFailSave = enabled;
}

export function resetSettingsSaveFailureForTest() {
  shouldFailSave = false;
}

export async function persistSettingsSave(): Promise<void> {
  await new Promise((resolve) => {
    window.setTimeout(resolve, 20);
  });

  if (shouldFailSave) {
    throw new Error("settings-save-failed");
  }
}
