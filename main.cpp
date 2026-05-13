#include <algorithm>
#include <cctype>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

enum class Clef {
    Treble,
    Bass,
    Alto
};

struct Note {
    std::string input;
    char letter;
    int accidental;
    int octave;
    int midi;
};

std::string trim(const std::string& text) {
    const auto first = text.find_first_not_of(" \t\r\n");
    if (first == std::string::npos) {
        return "";
    }

    const auto last = text.find_last_not_of(" \t\r\n");
    return text.substr(first, last - first + 1);
}

int pitchClassForLetter(char letter) {
    switch (std::toupper(static_cast<unsigned char>(letter))) {
        case 'C': return 0;
        case 'D': return 2;
        case 'E': return 4;
        case 'F': return 5;
        case 'G': return 7;
        case 'A': return 9;
        case 'B': return 11;
        default: throw std::invalid_argument("Invalid note letter.");
    }
}

int diatonicIndexForLetter(char letter) {
    switch (std::toupper(static_cast<unsigned char>(letter))) {
        case 'C': return 0;
        case 'D': return 1;
        case 'E': return 2;
        case 'F': return 3;
        case 'G': return 4;
        case 'A': return 5;
        case 'B': return 6;
        default: throw std::invalid_argument("Invalid note letter.");
    }
}

Note parseNote(const std::string& token) {
    const std::string cleaned = trim(token);
    if (cleaned.size() < 2) {
        throw std::invalid_argument("Note is too short: " + token);
    }

    const char letter = cleaned[0];
    int index = 1;
    int accidental = 0;

    if (index < static_cast<int>(cleaned.size()) &&
        (cleaned[index] == '#' || cleaned[index] == 'b' || cleaned[index] == 'B')) {
        accidental = (cleaned[index] == '#') ? 1 : -1;
        ++index;
    }

    const std::string octaveText = cleaned.substr(index);
    if (octaveText.empty()) {
        throw std::invalid_argument("Missing octave in note: " + token);
    }

    const int octave = std::stoi(octaveText);
    const int midi = (octave + 1) * 12 + pitchClassForLetter(letter) + accidental;

    return {cleaned, static_cast<char>(std::toupper(static_cast<unsigned char>(letter))), accidental, octave, midi};
}

std::string noteNameFromParts(char letter, int accidental, int octave) {
    std::string name(1, static_cast<char>(std::toupper(static_cast<unsigned char>(letter))));
    if (accidental == 1) {
        name += "#";
    } else if (accidental == -1) {
        name += "b";
    }
    name += std::to_string(octave);
    return name;
}

std::string midiToNoteName(int midi) {
    static const std::vector<std::string> names = {
        "C", "C#", "D", "D#", "E", "F",
        "F#", "G", "G#", "A", "A#", "B"
    };

    const int pitchClass = ((midi % 12) + 12) % 12;
    const int octave = midi / 12 - 1;
    return names[pitchClass] + std::to_string(octave);
}

int adjustForCello(int midi) {
    constexpr int celloLow = 36;   // C2
    constexpr int celloHigh = 76;  // E5
    constexpr int comfortableHigh = 69; // A4

    while (midi > comfortableHigh && midi - 12 >= celloLow) {
        midi -= 12;
    }

    while (midi < celloLow && midi + 12 <= celloHigh) {
        midi += 12;
    }

    return std::clamp(midi, celloLow, celloHigh);
}

Clef parseClef(const std::string& name) {
    if (name == "treble") {
        return Clef::Treble;
    }
    if (name == "bass") {
        return Clef::Bass;
    }
    if (name == "alto") {
        return Clef::Alto;
    }

    throw std::invalid_argument("Unknown clef: " + name);
}

std::string clefName(Clef clef) {
    switch (clef) {
        case Clef::Treble: return "treble";
        case Clef::Bass: return "bass";
        case Clef::Alto: return "alto";
    }

    throw std::invalid_argument("Unsupported clef.");
}

int bottomLineDiatonicIndex(Clef clef) {
    switch (clef) {
        case Clef::Treble: return 4 * 7 + diatonicIndexForLetter('E'); // E4
        case Clef::Bass: return 2 * 7 + diatonicIndexForLetter('G');   // G2
        case Clef::Alto: return 3 * 7 + diatonicIndexForLetter('F');   // F3
    }

    throw std::invalid_argument("Unsupported clef.");
}

int diatonicIndexForNote(const Note& note) {
    return note.octave * 7 + diatonicIndexForLetter(note.letter);
}

std::string describeStaffPosition(Clef clef, const Note& note) {
    const int relative = diatonicIndexForNote(note) - bottomLineDiatonicIndex(clef);

    if (relative >= 0 && relative <= 8) {
        if (relative % 2 == 0) {
            return "line " + std::to_string(relative / 2 + 1) + " of the staff";
        }
        return "space " + std::to_string(relative / 2 + 1) + " of the staff";
    }

    if (relative < 0) {
        const int distance = -relative;
        if (distance % 2 == 0) {
            return std::to_string(distance / 2) + " ledger line(s) below the staff";
        }
        return "ledger space below the staff";
    }

    const int distance = relative - 8;
    if (distance % 2 == 0) {
        return std::to_string(distance / 2) + " ledger line(s) above the staff";
    }
    return "ledger space above the staff";
}

std::vector<std::string> splitNotes(const std::string& line) {
    std::istringstream input(line);
    std::vector<std::string> notes;
    std::string token;

    while (input >> token) {
        notes.push_back(token);
    }

    return notes;
}

void printUsage(const char* programName) {
    std::cout << "Usage:\n";
    std::cout << "  " << programName << " --mode translate --from treble --to bass \"A4 B4 C5\"\n";
    std::cout << "  " << programName << " --mode translate --from bass --to alto \"F2 C3 G3\"\n";
    std::cout << "  " << programName << " --mode arrange \"E5 F5 G5 A5\"\n";
    std::cout << "\nModes:\n";
    std::cout << "  translate  Preserve pitch and show how it sits in another clef.\n";
    std::cout << "  arrange    Shift notes by octave when needed for cello-friendly range.\n";
    std::cout << "\nSupported clefs:\n";
    std::cout << "  treble (高音谱号), bass (低音谱号), alto (中音谱号)\n";
}

int main(int argc, char* argv[]) {
    try {
        if (argc == 4 && std::string(argv[1]) == "--mode" && std::string(argv[2]) == "arrange") {
            const std::string inputLine = argv[3];
            const auto tokens = splitNotes(inputLine);
            if (tokens.empty()) {
                throw std::invalid_argument("No notes provided.");
            }

            std::cout << "Input mode: arrange\n\n";

            for (const std::string& token : tokens) {
                const Note note = parseNote(token);
                const int outputMidi = adjustForCello(note.midi);

                std::cout << "Input:  " << note.input << " (" << note.midi << ")\n";
                std::cout << "Output: " << midiToNoteName(outputMidi) << " (" << outputMidi << ")\n";
                if (outputMidi != note.midi) {
                    std::cout << "Rule:   shifted by octave for cello comfort\n";
                } else {
                    std::cout << "Rule:   kept original pitch\n";
                }
                std::cout << "\n";
            }

            return 0;
        }

        if (argc == 8 &&
            std::string(argv[1]) == "--mode" &&
            std::string(argv[2]) == "translate" &&
            std::string(argv[3]) == "--from" &&
            std::string(argv[5]) == "--to") {
            const Clef fromClef = parseClef(argv[4]);
            const Clef toClef = parseClef(argv[6]);
            const std::string inputLine = argv[7];
            const auto tokens = splitNotes(inputLine);
            if (tokens.empty()) {
                throw std::invalid_argument("No notes provided.");
            }

            std::cout << "Input mode: translate\n";
            std::cout << "From: " << clefName(fromClef) << "\n";
            std::cout << "To:   " << clefName(toClef) << "\n\n";

            for (const std::string& token : tokens) {
                const Note note = parseNote(token);

                std::cout << "Pitch:  " << noteNameFromParts(note.letter, note.accidental, note.octave)
                          << " (" << note.midi << ")\n";
                std::cout << "From:   " << describeStaffPosition(fromClef, note) << "\n";
                std::cout << "To:     " << describeStaffPosition(toClef, note) << "\n";
                std::cout << "Rule:   preserved pitch, changed clef only\n\n";
            }

            return 0;
        }

        printUsage(argv[0]);
        return 1;
    } catch (const std::exception& error) {
        std::cerr << "Error: " << error.what() << "\n";
        return 1;
    }
}
