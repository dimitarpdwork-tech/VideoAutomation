import {createProfile, connectChannel, cancelConnection, produce, saveSettings, addStory, preschedule, generateStories,
  autopilot, saveApiKey, markRelatedDone, review, editTitle, makeVoiceSamples, exportTikTok, savePexelsKey, openFolder,
  designVoice, keepDesign, characterPreviews, draftPersona,
  isLocalRequest} from '../../../lib/studio';

const actions = {
  'create': body => createProfile(body.id, body.name, body.preset),
  'connect': body => connectChannel(body.channel),
  'cancel-connect': body => cancelConnection(body.channel),
  'produce': body => produce(body.channel, body.count),
  'settings': body => saveSettings(body.channel, body.settings),
  'add-story': body => addStory(body.channel, body.title, body.text),
  'preschedule': body => preschedule(body.channel, body.count),
  'generate': body => generateStories(body.channel, body.count),
  'autopilot': body => autopilot(body.channel, body.count),
  'api-key': body => saveApiKey(body.key, body.confirmRemove === true),
  'related-done': body => markRelatedDone(body.channel, body.teaserId),
  'review': body => review(body.channel, body.batch, body.names, body.decision, body.note),
  'edit-title': body => editTitle(body.channel, body.batch, body.name, body.title),
  'voice-samples': body => makeVoiceSamples(body.channel),
  'tiktok': body => exportTikTok(body.channel),
  'pexels-key': body => savePexelsKey(body.key, body.confirmRemove === true),
  'open-folder': body => openFolder(body.channel, body.which),
  'design-voice': body => designVoice(body.channel, body.description, body.count),
  'keep-design': body => keepDesign(body.channel, body.file, body.name),
  'character-previews': body => characterPreviews(body.channel, body.sample),
  'draft-persona': body => draftPersona(body.channel, body.clip, body.description),
};

export async function POST(request) {
  if (!isLocalRequest(request)) return Response.json({error: 'Only dashboard requests are allowed.'}, {status: 403});
  try {
    const body = await request.json();
    const action = actions[body.action];
    if (!action) throw Error('Unknown action');
    return Response.json(await action(body));
  } catch (error) {
    return Response.json({error: error.message}, {status: 400});
  }
}
