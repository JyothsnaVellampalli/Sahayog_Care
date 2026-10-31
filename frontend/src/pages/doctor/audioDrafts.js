// Only uploads not yet acknowledged by the API remain in the browser database.
function database() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open('sahayog-audio-uploads', 1);
    request.onupgradeneeded = () => request.result.createObjectStore('recordings');
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}
async function transaction(visitId, operation, value) {
  const db = await database();
  try {
    return await new Promise((resolve, reject) => {
      const tx = db.transaction('recordings', operation === 'get' ? 'readonly' : 'readwrite');
      const store = tx.objectStore('recordings');
      const request = operation === 'put' ? store.put(value, visitId) : store[operation](visitId);
      tx.oncomplete = () => resolve(request.result);
      tx.onerror = () => reject(tx.error);
      tx.onabort = () => reject(tx.error || new Error('Recording save interrupted'));
    });
  } finally { db.close(); }
}
export const loadAudioDraft = visitId => transaction(visitId, 'get');
export const saveAudioDraft = (visitId, item) => transaction(visitId, 'put', item);
export const deleteAudioDraft = visitId => transaction(visitId, 'delete');
