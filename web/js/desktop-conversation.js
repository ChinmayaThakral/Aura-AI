// Keep one stable, chronological conversation so updates do not reset reading.
export function createConversationRenderer(container, doc = document) {
    let session = null;
    let cards = [];

    function renderAnswer(body, text) {
        const fragment = doc.createDocumentFragment();
        String(text || '').split('```').forEach((part, index) => {
            if (index % 2) {
                const pre = doc.createElement('pre');
                const code = doc.createElement('code');
                code.textContent = part.replace(/^[\w+-]*\r?\n/, '');
                pre.appendChild(code);
                fragment.appendChild(pre);
            } else if (part) {
                const paragraph = doc.createElement('p');
                paragraph.textContent = part;
                fragment.appendChild(paragraph);
            }
        });
        body.replaceChildren(fragment);
    }

    return state => {
        const follow = container.scrollHeight - container.scrollTop - container.clientHeight < 80;
        const scrollTop = container.scrollTop;
        const changedSession = session !== state.session_id;
        if (changedSession) {
            session = state.session_id;
            cards = [];
            container.replaceChildren();
        }
        const items = [...(state.history || [])];
        if (state.question || state.answer || state.answering) {
            items.push({question: state.question, answer: state.answer, answering: state.answering});
        }
        while (cards.length > items.length) cards.pop().article.remove();
        items.forEach((item, index) => {
            if (!cards[index]) {
                const article = doc.createElement('article');
                const heading = doc.createElement('h2');
                const body = doc.createElement('div');
                const progress = doc.createElement('small');
                article.className = 'conversation-turn';
                body.className = 'turn-answer';
                progress.className = 'answer-progress';
                article.append(heading, body, progress);
                container.appendChild(article);
                cards[index] = {article, heading, body, progress};
            }
            const card = cards[index];
            const question = item.question || 'Question';
            if (card.heading.textContent !== question) card.heading.textContent = question;
            if (card.answer !== item.answer) {
                renderAnswer(card.body, item.answer);
                card.answer = item.answer;
            }
            card.progress.textContent = item.answering ? 'Generating…' : '';
        });
        if (changedSession || follow) container.scrollTop = container.scrollHeight;
        else container.scrollTop = scrollTop;
    };
}
